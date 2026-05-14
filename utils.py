import os
from gtts import gTTS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from database import conectar, total_ventas_dia, total_ventas_mes, obtener_meta_activa
from datetime import date

AUDIO_DIR = "audio_responses"
CHART_DIR = "static/charts"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)

def texto_a_audio(texto, filename):
    path = os.path.join(AUDIO_DIR, filename)
    tts = gTTS(text=texto, lang='es')
    tts.save(path)
    return path

def generar_grafico_ventas_mes(negocio_id, mes=None, año=None):
    if mes is None:
        mes = date.today().month
    if año is None:
        año = date.today().year
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        SELECT fecha, SUM(total) FROM ventas
        WHERE negocio_id=%s AND to_char(fecha::date, 'YYYY-MM')=%s
        GROUP BY fecha ORDER BY fecha
    """, (negocio_id, f"{año}-{mes:02d}"))
    datos = cur.fetchall()
    conn.close()
    if not datos:
        return None
    fechas = [row[0] for row in datos]
    totales = [row[1] for row in datos]
    plt.figure(figsize=(10, 5))
    plt.bar(fechas, totales, color='royalblue')
    plt.title(f"Ventas diarias – {año}-{mes:02d}")
    plt.xticks(rotation=45)
    plt.tight_layout()
    filename = f"ventas_mes_{negocio_id}_{año}_{mes:02d}.png"
    path = os.path.join(CHART_DIR, filename)
    plt.savefig(path)
    plt.close()
    return filename

def generar_grafico_progreso(negocio_id, tipo="diaria"):
    if tipo == "diaria":
        actual = total_ventas_dia(negocio_id)
        meta = obtener_meta_activa(negocio_id, "diaria") or 0
    else:
        actual = total_ventas_mes(negocio_id, date.today().year, date.today().month)
        meta = obtener_meta_activa(negocio_id, "mensual") or 0
    if meta == 0:
        return None
    plt.figure(figsize=(6, 4))
    plt.barh(["Progreso"], [actual], color='green')
    plt.barh(["Meta"], [meta], color='lightgray')
    plt.xlim(0, meta*1.2)
    plt.title(f"Progreso meta {tipo}")
    filename = f"progreso_{negocio_id}_{tipo}.png"
    path = os.path.join(CHART_DIR, filename)
    plt.savefig(path)
    plt.close()
    return filename
