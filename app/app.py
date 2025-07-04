from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
from pathlib import Path
import os
import pdfkit
from pdfkit.configuration import Configuration
import pandas as pd
from .utils.db import get_connection

PDFKIT_CONFIG = Configuration(wkhtmltopdf="/usr/bin/wkhtmltopdf")
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.on_event("startup")
def crear_tablas():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS consumibles (
        codigo_hoja TEXT PRIMARY KEY,
        nombre_mostrado TEXT NOT NULL,
        categoria TEXT NOT NULL CHECK (categoria IN ('carton', 'plastico', 'aditivo', 'sal', 'agua'))
    )
    """)

    cursor.execute("ALTER TABLE consumibles ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT TRUE")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimientos (
        id SERIAL PRIMARY KEY,
        fecha TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida')),
        id_lote TEXT NOT NULL,
        documento TEXT NOT NULL,
        nombre_consumible TEXT NOT NULL REFERENCES consumibles(codigo_hoja),
        entrada REAL,
        salida REAL,
        existencias REAL,
        precio_unitario REAL
    )
    """)

    conn.commit()
    conn.close()

@app.get("/")
def menu(request: Request):
    return templates.TemplateResponse("menu.html", {"request": request})

@app.get("/consumibles", response_class=HTMLResponse)
def gestionar_consumibles(request: Request):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo_hoja, nombre_mostrado, categoria FROM consumibles WHERE activo = TRUE ORDER BY categoria, nombre_mostrado")
    consumibles = cursor.fetchall()
    conn.close()
    return templates.TemplateResponse("consumibles.html", {"request": request, "consumibles": consumibles})

@app.post("/consumibles/agregar")
def agregar_consumible(nombre_mostrado: str = Form(...), codigo_hoja: str = Form(...), categoria: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO consumibles (codigo_hoja, nombre_mostrado, categoria)
        VALUES (%s, %s, %s)
        ON CONFLICT (codigo_hoja) DO UPDATE
        SET nombre_mostrado = EXCLUDED.nombre_mostrado,
            categoria = EXCLUDED.categoria
    """, (codigo_hoja, nombre_mostrado, categoria))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/consumibles", status_code=303)

@app.post("/consumibles/eliminar")
def archivar_consumible(codigo_hoja: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE consumibles SET activo = FALSE WHERE codigo_hoja = %s", (codigo_hoja,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/consumibles", status_code=303)

@app.get("/entrada", response_class=HTMLResponse)
def entrada_form(request: Request):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT categoria, nombre_mostrado, codigo_hoja FROM consumibles WHERE activo = TRUE")
    datos = cursor.fetchall()
    conn.close()

    consumibles = {}
    for categoria, nombre, codigo in datos:
        consumibles.setdefault(categoria, []).append((nombre, codigo))

    return templates.TemplateResponse("entrada.html", {
        "request": request,
        "consumibles": consumibles,
        "volver_menu": True,
        "mensaje": None
    })

@app.post("/entrada", response_class=HTMLResponse)
def registrar_entrada(
    request: Request,
    fecha: str = Form(...),
    codigo_lote: str = Form(...),
    cantidad: float = Form(...),
    precio_unitario: float = Form(...),
    codigo_consumible: str = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO movimientos (fecha, tipo, id_lote, documento, nombre_consumible, entrada, salida, existencias, precio_unitario)
        VALUES (%s, 'entrada', %s, %s, %s, %s, NULL, %s, %s)
    """, (fecha, codigo_lote, codigo_lote, codigo_consumible, cantidad, cantidad, precio_unitario))
    conn.commit()
    conn.close()
    return entrada_form(request=request)
@app.get("/salida", response_class=HTMLResponse)
def salida_form(request: Request, filtro_formato: str = "", mensaje: str = ""):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # ✅ CONSULTA CORREGIDA: solo 2 columnas (código y nombre)
        cursor.execute("SELECT codigo_hoja, nombre_mostrado FROM consumibles WHERE activo = TRUE")
        formatos_disponibles = cursor.fetchall()
        formatos_codigos = [f[0] for f in formatos_disponibles]  # f[0] = codigo_hoja

        if filtro_formato and filtro_formato not in formatos_codigos:
            mensaje = "⚠️ El formato seleccionado no existe o aún no tiene movimientos."
            filtro_formato = ""
            lotes = []
        else:
            lotes = []
            if filtro_formato:
                cursor.execute("""
                    SELECT id_lote,
                           SUM(COALESCE(entrada, 0)) - SUM(COALESCE(salida, 0)) AS stock
                    FROM movimientos
                    WHERE nombre_consumible = %s
                    GROUP BY id_lote
                    HAVING SUM(COALESCE(entrada, 0)) - SUM(COALESCE(salida, 0)) > 0
                """, (filtro_formato,))
                lotes = cursor.fetchall()

        conn.close()

        return templates.TemplateResponse("salida.html", {
            "request": request,
            "formatos": formatos_disponibles,
            "filtro_formato": filtro_formato,
            "lotes": lotes,
            "mensaje": mensaje,
            "volver_menu": True
        })

    except Exception as e:
        print(f"❌ Error en salida_form(): {e}")
        raise HTTPException(status_code=500, detail="Error interno en la carga de la página de salida.")



@app.post("/salida", response_class=HTMLResponse)
def registrar_salida(
    request: Request,
    fecha: str = Form(...),
    nombre_consumible: str = Form(...),
    id_lote: str = Form(...),
    documento: str = Form(...),
    cantidad: float = Form(...)
):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Verificar stock disponible
        cursor.execute("""
            SELECT SUM(COALESCE(entrada, 0)) - SUM(COALESCE(salida, 0))
            FROM movimientos
            WHERE nombre_consumible = %s AND id_lote = %s
        """, (nombre_consumible, id_lote))
        stock_disponible = cursor.fetchone()[0] or 0

        if cantidad > stock_disponible:
            mensaje = f"❌ No hay suficiente stock. Disponible: {stock_disponible:.2f} uds."
        else:
            cursor.execute("""
                INSERT INTO movimientos (fecha, tipo, id_lote, documento, nombre_consumible, entrada, salida, existencias, precio_unitario)
                VALUES (%s, 'salida', %s, %s, %s, NULL, %s, NULL, NULL)
            """, (fecha, id_lote, documento, nombre_consumible, cantidad))
            conn.commit()
            mensaje = "✅ Salida registrada correctamente."

        conn.close()

        # Codificar el mensaje para la URL
        from urllib.parse import quote
        mensaje_encoded = quote(mensaje)

        return RedirectResponse(url=f"/salida?filtro_formato={nombre_consumible}&mensaje={mensaje_encoded}", status_code=303)

    except Exception as e:
        print(f"❌ Error en registrar_salida(): {e}")
        raise HTTPException(status_code=500, detail="Error al registrar la salida.")


@app.get("/stock", response_class=HTMLResponse)
def ver_stock(request: Request, filtro_formato: str = "", filtro_lote: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nombre_consumible, id_lote,
               SUM(COALESCE(entrada, 0)) - SUM(COALESCE(salida, 0)) AS stock,
               MAX(CASE WHEN tipo = 'entrada' THEN precio_unitario ELSE NULL END) as precio_unitario
        FROM movimientos
        GROUP BY nombre_consumible, id_lote
        HAVING SUM(COALESCE(entrada, 0)) - SUM(COALESCE(salida, 0)) > 0
    """)
    resultados = cursor.fetchall()

    cursor.execute("SELECT codigo_hoja, nombre_mostrado FROM consumibles ORDER BY nombre_mostrado")
    formatos_disponibles = cursor.fetchall()

    lotes_disponibles = []
    if filtro_formato:
        cursor.execute("SELECT DISTINCT id_lote FROM movimientos WHERE nombre_consumible = %s AND tipo = 'entrada'", (filtro_formato,))
        lotes_disponibles = [row[0] for row in cursor.fetchall()]

    conn.close()

    filtrados = [r for r in resultados if (filtro_formato == "" or filtro_formato == r[0]) and (filtro_lote == "" or filtro_lote == r[1])]

    return templates.TemplateResponse("stock.html", {
        "request": request,
        "stock": filtrados,
        "filtro_formato": filtro_formato,
        "filtro_lote": filtro_lote,
        "formatos": formatos_disponibles,
        "lotes": lotes_disponibles,
        "volver_menu": True
    })

@app.get("/stock/informe-pdf")
def generar_informe_pdf():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.nombre_mostrado, m.nombre_consumible, m.id_lote,
               SUM(COALESCE(m.entrada, 0)) - SUM(COALESCE(m.salida, 0)) as stock,
               MAX(CASE WHEN tipo = 'entrada' THEN precio_unitario ELSE NULL END) as precio
        FROM movimientos m
        JOIN consumibles c ON m.nombre_consumible = c.codigo_hoja
        GROUP BY m.nombre_consumible, m.id_lote, c.nombre_mostrado
        HAVING SUM(COALESCE(m.entrada, 0)) - SUM(COALESCE(m.salida, 0)) > 0
        ORDER BY c.nombre_mostrado, m.id_lote
    """)
    datos = cursor.fetchall()
    conn.close()

    html = f"""
    <!DOCTYPE html>
    <html lang='es'>
    <head>
        <meta charset='UTF-8'>
        <style>
            body {{ font-family: 'DejaVu Sans', Arial, sans-serif; }}
            h1 {{ text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
            th, td {{ border: 1px solid #ccc; padding: 8px; text-align: center; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h1>Informe de stock - {datetime.now().strftime('%d/%m/%Y %H:%M')}</h1>
    """

    resumen = {}
    for nombre_mostrado, codigo, lote, stock, precio in datos:
        resumen.setdefault(nombre_mostrado, []).append((lote, stock, precio))

    for nombre, items in resumen.items():
        html += f"<h2>{nombre}</h2><table><tr><th>Lote</th><th>Stock</th><th>Precio Unitario (€)</th></tr>"
        total = 0
        for lote, stock, precio in items:
            precio_str = f"{precio:.4f}" if precio else "N/A"
            html += f"<tr><td>{lote}</td><td>{stock:.2f}</td><td>{precio_str}</td></tr>"
            total += stock
        html += f"<tr><th colspan='2'>Total</th><th>{total:.2f}</th></tr></table>"

    html += "</body></html>"

    output_path = BASE_DIR / "static" / "informe_stock.pdf"
    pdfkit.from_string(html, str(output_path), configuration=PDFKIT_CONFIG)
    return FileResponse(path=output_path, filename="informe_stock.pdf", media_type="application/pdf")

@app.get("/movimientos/exportar")
def exportar_movimientos_excel():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM movimientos", conn)
    conn.close()

    output_path = BASE_DIR / "static" / "movimientos.xlsx"
    df.to_excel(output_path, index=False)

    return FileResponse(path=output_path, filename="movimientos.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

