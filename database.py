import os
import psycopg2
from datetime import date, datetime

def conectar():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise Exception("Falta la variable de entorno DATABASE_URL")
    return psycopg2.connect(DATABASE_URL)

def crear_tablas():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS negocios (
            id SERIAL PRIMARY KEY,
            numero TEXT UNIQUE,
            nombre TEXT,
            moneda TEXT DEFAULT 'COP',
            meta_diaria REAL DEFAULT 0,
            meta_mensual REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            negocio_id INTEGER REFERENCES negocios(id),
            nombre TEXT,
            precio_por_defecto REAL,
            stock_actual INTEGER DEFAULT 0,
            stock_min INTEGER DEFAULT 5
        );
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            negocio_id INTEGER REFERENCES negocios(id),
            producto_id INTEGER REFERENCES productos(id),
            cantidad INTEGER,
            precio_unitario REAL,
            total REAL,
            fecha TEXT
        );
        CREATE TABLE IF NOT EXISTS metas (
            id SERIAL PRIMARY KEY,
            negocio_id INTEGER REFERENCES negocios(id),
            tipo TEXT,
            valor REAL,
            activa BOOLEAN DEFAULT TRUE,
            fecha_inicio TEXT
        );
    """)
    conn.commit()
    conn.close()

def obtener_o_crear_negocio(numero):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id FROM negocios WHERE numero=%s", (numero,))
    row = cur.fetchone()
    if row:
        negocio_id = row[0]
    else:
        cur.execute("INSERT INTO negocios (numero, nombre) VALUES (%s,%s) RETURNING id", (numero, "Mi Negocio"))
        negocio_id = cur.fetchone()[0]
        conn.commit()
    conn.close()
    return negocio_id

def registrar_venta(negocio_id, nombre_producto, cantidad, precio_unitario):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id, precio_por_defecto FROM productos WHERE negocio_id=%s AND nombre=%s", (negocio_id, nombre_producto))
    prod = cur.fetchone()
    if not prod:
        cur.execute("INSERT INTO productos (negocio_id, nombre, precio_por_defecto) VALUES (%s,%s,%s) RETURNING id",
                    (negocio_id, nombre_producto, precio_unitario))
        producto_id = cur.fetchone()[0]
        stock_actual = cantidad
    else:
        producto_id, precio_def = prod
        if precio_unitario is None or precio_unitario == 0:
            precio_unitario = precio_def
        if precio_unitario != precio_def:
            cur.execute("UPDATE productos SET precio_por_defecto=%s WHERE id=%s", (precio_unitario, producto_id))
        cur.execute("UPDATE productos SET stock_actual = stock_actual - %s WHERE id=%s", (cantidad, producto_id))
        cur.execute("SELECT stock_actual FROM productos WHERE id=%s", (producto_id,))
        stock_actual = cur.fetchone()[0]

    total = cantidad * precio_unitario
    fecha = date.today().isoformat()
    cur.execute("INSERT INTO ventas (negocio_id, producto_id, cantidad, precio_unitario, total, fecha) VALUES (%s,%s,%s,%s,%s,%s)",
                (negocio_id, producto_id, cantidad, precio_unitario, total, fecha))
    conn.commit()
    conn.close()
    return total, stock_actual

def total_ventas_dia(negocio_id, fecha_str=None):
    if fecha_str is None:
        fecha_str = date.today().isoformat()
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT SUM(total) FROM ventas WHERE negocio_id=%s AND fecha=%s", (negocio_id, fecha_str))
    total = cur.fetchone()[0] or 0
    conn.close()
    return total

def total_ventas_mes(negocio_id, anio, mes):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT SUM(total) FROM ventas WHERE negocio_id=%s AND to_char(fecha::date, 'YYYY-MM')=%s",
                (negocio_id, f"{anio:04d}-{mes:02d}"))
    total = cur.fetchone()[0] or 0
    conn.close()
    return total

def obtener_meta_activa(negocio_id, tipo):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT valor FROM metas WHERE negocio_id=%s AND tipo=%s AND activa=true ORDER BY id DESC LIMIT 1",
                (negocio_id, tipo))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def establecer_meta(negocio_id, tipo, valor):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE metas SET activa=false WHERE negocio_id=%s AND tipo=%s", (negocio_id, tipo))
    cur.execute("INSERT INTO metas (negocio_id, tipo, valor, activa, fecha_inicio) VALUES (%s,%s,%s,true,%s)",
                (negocio_id, tipo, valor, date.today().isoformat()))
    conn.commit()
    conn.close()

def resumen_historico(negocio_id, periodo):
    conn = conectar()
    cur = conn.cursor()
    if periodo == "ayer":
        from datetime import timedelta
        ayer = date.today() - timedelta(days=1)
        cur.execute("SELECT SUM(total) FROM ventas WHERE negocio_id=%s AND fecha=%s", (negocio_id, ayer.isoformat()))
    elif periodo == "este_mes":
        hoy = date.today()
        cur.execute("SELECT SUM(total) FROM ventas WHERE negocio_id=%s AND to_char(fecha::date, 'YYYY-MM')=%s",
                    (negocio_id, f"{hoy.year}-{hoy.month:02d}"))
    else:
        cur.execute("SELECT SUM(total) FROM ventas WHERE negocio_id=%s AND fecha=%s", (negocio_id, periodo))
    total = cur.fetchone()[0] or 0
    conn.close()
    return total
