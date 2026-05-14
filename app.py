import os
from flask import Flask, request, render_template, send_from_directory, url_for
from twilio.twiml.messaging_response import MessagingResponse
import requests
import openai
from database import *
from utils import texto_a_audio, generar_grafico_ventas_mes, generar_grafico_progreso
import json
import uuid

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

VOZ_SIEMPRE = False

def transcribir_audio(url_audio):
    resp = requests.get(url_audio)
    audio_path = "/tmp/audio.ogg"
    with open(audio_path, "wb") as f:
        f.write(resp.content)
    with open(audio_path, "rb") as audio_file:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=audio_file,
            language="es"
        )
    return transcript["text"].strip()

def interpretar_con_gpt(texto_usuario, negocio_id):
    system_prompt = """
Eres un asistente de un pequeño negocio. Interpreta los comandos del dueño y devuelve ÚNICAMENTE un JSON array válido, donde cada elemento es una acción. Cada acción tiene esta estructura:
{
  "accion": "...",
  "parametros": { ... }
}

Acciones disponibles:
- "registrar_venta": productos (lista de objetos con nombre, cantidad, precio_unitario opcional)
- "establecer_meta": tipo ("diaria"/"mensual"), valor (número)
- "consultar_progreso": tipo ("diaria"/"mensual", opcional)
- "consultar_stock": producto (nombre)
- "consultar_historico": periodo ("ayer", "este_mes", "YYYY-MM-DD")
- "grafico_ventas_mes": mes (número, opcional), año (número, opcional)
- "grafico_progreso": tipo ("diaria"/"mensual")
- "saludo"
- "no_entendido"

Ejemplo:
Usuario: "Vendí 3 gaseosas a 2500, ¿cuántas me quedan? Y pon meta diaria 80000"
Respuesta JSON:
[
  {"accion":"registrar_venta","parametros":{"productos":[{"nombre":"gaseosa","cantidad":3,"precio_unitario":2500}]}},
  {"accion":"consultar_stock","parametros":{"producto":"gaseosa"}},
  {"accion":"establecer_meta","parametros":{"tipo":"diaria","valor":80000}}
]

Responde solo con el JSON array, sin texto adicional.
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": texto_usuario}
            ],
            temperature=0,
            max_tokens=400
        )
        contenido = response.choices[0].message.content
        comandos = json.loads(contenido)
        if isinstance(comandos, dict):
            comandos = [comandos]
        return comandos
    except Exception as e:
        return [{"accion": "error", "parametros": {"mensaje": str(e)}}]

def ejecutar_comandos(lista_comandos, negocio_id):
    respuestas_texto = []
    media_urls = []

    for cmd in lista_comandos:
        accion = cmd.get("accion")
        params = cmd.get("parametros", {})

        if accion == "registrar_venta":
            for p in params.get("productos", []):
                nombre = p["nombre"]
                cantidad = p["cantidad"]
                precio = p.get("precio_unitario", 0.0)
                total, stock = registrar_venta(negocio_id, nombre, cantidad, precio)
                respuestas_texto.append(f"✔ {cantidad} {nombre} por ${total:.0f}")
            total_dia = total_ventas_dia(negocio_id)
            meta_diaria = obtener_meta_activa(negocio_id, "diaria")
            mensaje = f"Total hoy: ${total_dia:.0f}."
            if meta_diaria:
                falta = meta_diaria - total_dia
                mensaje += f" {'Faltan' if falta>0 else '¡Meta cumplida!'} ${falta:.0f}" if falta>0 else " ¡Meta cumplida!"
            respuestas_texto.append(mensaje)

        elif accion == "establecer_meta":
            tipo = params["tipo"]
            valor = params["valor"]
            establecer_meta(negocio_id, tipo, valor)
            respuestas_texto.append(f"🎯 Meta {tipo} establecida en ${valor:.0f}")

        elif accion == "consultar_progreso":
            tipo = params.get("tipo", "diaria")
            if tipo == "diaria":
                actual = total_ventas_dia(negocio_id)
            else:
                actual = total_ventas_mes(negocio_id, date.today().year, date.today().month)
            meta = obtener_meta_activa(negocio_id, tipo)
            if meta:
                respuestas_texto.append(f"📊 Progreso {tipo}: ${actual:.0f} de ${meta:.0f}")
            else:
                respuestas_texto.append(f"📊 Llevas ${actual:.0f}. No hay meta {tipo}.")

        elif accion == "consultar_stock":
            prod = params["producto"]
            conn = conectar()
            cur = conn.cursor()
            cur.execute("SELECT stock_actual FROM productos WHERE negocio_id=%s AND nombre LIKE %s",
                        (negocio_id, f"%{prod}%"))
            row = cur.fetchone()
            conn.close()
            if row:
                respuestas_texto.append(f"📦 {prod}: {row[0]} unidades")
            else:
                respuestas_texto.append(f"❌ Producto '{prod}' no encontrado.")

        elif accion == "consultar_historico":
            periodo = params["periodo"]
            total = resumen_historico(negocio_id, periodo)
            if periodo == "ayer":
                respuestas_texto.append(f"📅 Ayer vendiste ${total:.0f}")
            elif periodo == "este_mes":
                respuestas_texto.append(f"📅 Este mes: ${total:.0f}")
            else:
                respuestas_texto.append(f"📅 {periodo}: ${total:.0f}")

        elif accion == "grafico_ventas_mes":
            mes = params.get("mes", date.today().month)
            año = params.get("año", date.today().year)
            filename = generar_grafico_ventas_mes(negocio_id, mes, año)
            if filename:
                url = url_for('static', filename=f'charts/{filename}', _external=True)
                media_urls.append(url)
                respuestas_texto.append(f"📈 Gráfico de ventas del {año}-{mes:02d} generado.")
            else:
                respuestas_texto.append("No hay datos para ese período.")

        elif accion == "grafico_progreso":
            tipo = params.get("tipo", "diaria")
            filename = generar_grafico_progreso(negocio_id, tipo)
            if filename:
                url = url_for('static', filename=f'charts/{filename}', _external=True)
                media_urls.append(url)
                respuestas_texto.append(f"📊 Gráfico de progreso {tipo}.")
            else:
                respuestas_texto.append("No hay meta establecida para generar el gráfico.")

        elif accion == "saludo":
            respuestas_texto.append("¡Hola! Soy tu Libreta Digital. Dime qué necesitas.")

        elif accion == "error":
            respuestas_texto.append("⚠️ Error interno: " + params.get("mensaje", "desconocido"))

        else:
            respuestas_texto.append("No pude interpretar esa parte.")

    texto_final = "\n".join(respuestas_texto) if respuestas_texto else "Comando procesado."
    return texto_final, media_urls

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    numero = request.values.get("From", "")
    media_url = request.values.get("MediaUrl0", "")
    body = request.values.get("Body", "").strip()

    es_audio = bool(media_url and media_url.endswith(".ogg"))
    if es_audio:
        texto = transcribir_audio(media_url)
    else:
        texto = body

    if not texto:
        respuesta = "Envía un mensaje de voz o texto."
        return str(MessagingResponse().message(respuesta))

    negocio_id = obtener_o_crear_negocio(numero)
    comandos = interpretar_con_gpt(texto, negocio_id)
    texto_respuesta, media_urls = ejecutar_comandos(comandos, negocio_id)

    twiml = MessagingResponse()

    if (es_audio or VOZ_SIEMPRE) and texto_respuesta:
        filename = f"resp_{uuid.uuid4().hex}.mp3"
        audio_path = texto_a_audio(texto_respuesta, filename)
        audio_url = url_for('audio', filename=filename, _external=True)
        twiml.message().media(audio_url)
        if len(texto_respuesta) > 160:
            twiml.message(texto_respuesta[:160] + "... (audio completo)")
        else:
            twiml.message(texto_respuesta)
    else:
        twiml.message(texto_respuesta)

    for img_url in media_urls:
        twiml.message().media(img_url)

    return str(twiml)

@app.route("/audio/<filename>")
def audio(filename):
    return send_from_directory("audio_responses", filename)

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/ventas_dia")
def api_ventas_dia():
    total = total_ventas_dia(1)
    return {"total": total}

@app.route("/api/ventas_mes")
def api_ventas_mes():
    conn = conectar()
    cur = conn.cursor()
    hoy = date.today()
    cur.execute("SELECT fecha, SUM(total) FROM ventas WHERE negocio_id=1 AND to_char(fecha::date, 'YYYY-MM')=%s GROUP BY fecha",
                (f"{hoy.year}-{hoy.month:02d}",))
    datos = [{"fecha": row[0], "total": row[1]} for row in cur.fetchall()]
    conn.close()
    return {"ventas": datos}

@app.route("/api/inventario")
def api_inventario():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT nombre, stock_actual FROM productos WHERE negocio_id=1")
    inventario = [{"nombre": row[0], "stock": row[1]} for row in cur.fetchall()]
    conn.close()
    return {"productos": inventario}

@app.route("/api/progreso")
def api_progreso():
    actual = total_ventas_dia(1)
    meta = obtener_meta_activa(1, "diaria") or 0
    return {"actual": actual, "meta": meta}

@app.route("/")
def index():
    return render_template("index.html")
