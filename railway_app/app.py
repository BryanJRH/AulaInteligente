import os
import sqlite3
from datetime import datetime
from threading import Lock

from flask import Flask, request, jsonify, render_template, send_file

app = Flask(__name__)

# Clave secreta: debe coincidir con TOKEN_WEB del ESP32.
# Se configura en Railway como variable de entorno llamada SECRETO.
SECRETO = os.environ.get("SECRETO", "")

# Directorio donde se guarda la base de datos.
# Si montas un Volumen en /data, los datos sobreviven a los re-despliegues.
DATA_DIR = os.environ.get("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "aula.db")

lock = Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with lock:
        conn = get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lecturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                hora TEXT,
                temp REAL,
                hum REAL,
                co2 INTEGER,
                intake INTEGER,
                extractor INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comandos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                texto TEXT,
                creado TEXT,
                estado TEXT DEFAULT 'pendiente',
                respuesta TEXT
            )
        """)
        conn.commit()
        conn.close()


init_db()


def hora_actual():
    return datetime.now().astimezone()


# ---------------- Página ----------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------- Datos del ESP32 ----------------
@app.route("/api/datos", methods=["POST"])
def recibir_datos():
    """El ESP32 manda aqui cada lectura."""
    datos = request.get_json(silent=True) or {}
    if SECRETO and datos.get("clave") != SECRETO:
        return jsonify({"ok": False, "error": "clave invalida"}), 401

    ahora = hora_actual()
    with lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO lecturas (ts, hora, temp, hum, co2, intake, extractor) "
            "VALUES (?,?,?,?,?,?,?)",
            (ahora.timestamp(), ahora.isoformat(timespec="seconds"),
             datos.get("temp"), datos.get("hum"), datos.get("co2"),
             datos.get("intake"), datos.get("extractor")),
        )
        conn.commit()
        conn.close()
    return jsonify({"ok": True}), 201


@app.route("/api/datos", methods=["GET"])
def entregar_datos():
    """La pagina web pide aqui los datos para actualizarse."""
    with lock:
        conn = get_db()
        filas = conn.execute(
            "SELECT * FROM lecturas ORDER BY id DESC LIMIT 120"
        ).fetchall()
        conn.close()
    lista = [dict(f) for f in reversed(filas)]
    return jsonify({
        "ultima": lista[-1] if lista else None,
        "historial": lista,
    })


# ---------------- Comandos (chat web -> ESP32) ----------------
@app.route("/api/comandos", methods=["POST"])
def enviar_comando():
    """El chat de la web manda un comando para el ESP32."""
    datos = request.get_json(silent=True) or {}
    texto = (datos.get("texto") or "").strip()
    if not texto:
        return jsonify({"ok": False, "error": "texto vacio"}), 400
    # NOTA: es un demo; el chat no pide clave. Cualquiera con la URL del
    # dashboard puede mandar comandos mientras tanto. Se puede proteger
    # despues con una clave web.
    with lock:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO comandos (texto, creado, estado) VALUES (?,?,?)",
            (texto, hora_actual().isoformat(timespec="seconds"), "pendiente"),
        )
        conn.commit()
        nuevo_id = cur.lastrowid
        conn.close()
    return jsonify({"ok": True, "id": nuevo_id}), 201


@app.route("/api/comandos", methods=["GET"])
def leer_comandos():
    """El ESP32 viene a buscar comandos pendientes."""
    clave = request.args.get("clave", "")
    if SECRETO and clave != SECRETO:
        return jsonify({"ok": False, "error": "clave invalida"}), 401
    with lock:
        conn = get_db()
        filas = conn.execute(
            "SELECT * FROM comandos WHERE estado='pendiente' ORDER BY id"
        ).fetchall()
        conn.execute(
            "UPDATE comandos SET estado='entregado' WHERE estado='pendiente'"
        )
        conn.commit()
        conn.close()
    return jsonify({"ok": True, "comandos": [dict(f) for f in filas]})


@app.route("/api/respuesta", methods=["POST"])
def registrar_respuesta():
    """El ESP32 confirma un comando con su respuesta."""
    datos = request.get_json(silent=True) or {}
    if SECRETO and datos.get("clave") != SECRETO:
        return jsonify({"ok": False, "error": "clave invalida"}), 401
    cid = datos.get("id")
    if cid is None:
        return jsonify({"ok": False, "error": "falta id"}), 400
    respuesta = (datos.get("respuesta") or "").strip()
    with lock:
        conn = get_db()
        conn.execute(
            "UPDATE comandos SET estado='respondido', respuesta=? WHERE id=?",
            (respuesta, cid),
        )
        conn.commit()
        conn.close()
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["GET"])
def chat():
    """El chat de la web listo los comandos y sus respuestas."""
    with lock:
        conn = get_db()
        filas = conn.execute(
            "SELECT * FROM comandos ORDER BY id DESC LIMIT 50"
        ).fetchall()
        conn.close()
    return jsonify({"comandos": [dict(f) for f in reversed(filas)]})


# ---------------- Historial (ver la base de datos) ----------------
NOMBRES_NIVEL = {0: "Apagado", 1: "Bajo (5V)", 2: "Alto (12V)"}


@app.route("/historial")
def historial():
    """Pagina web con la tabla de todas las lecturas guardadas."""
    with lock:
        conn = get_db()
        filas = conn.execute(
            "SELECT * FROM lecturas ORDER BY id DESC LIMIT 300"
        ).fetchall()
        conn.close()
    lista = []
    for f in reversed(filas):
        f = dict(f)
        f["intake_txt"] = NOMBRES_NIVEL.get(f["intake"], "?")
        f["extractor_txt"] = NOMBRES_NIVEL.get(f["extractor"], "?")
        lista.append(f)
    return render_template("historial.html", filas=lista)


@app.route("/api/historial")
def historial_json():
    """Los datos guardados en JSON (los ultimos 500)."""
    with lock:
        conn = get_db()
        filas = conn.execute(
            "SELECT * FROM lecturas ORDER BY id DESC LIMIT 500"
        ).fetchall()
        conn.close()
    return jsonify({"lecturas": [dict(f) for f in reversed(filas)]})


@app.route("/api/descargar")
def descargar_db():
    """Descarga el archivo .db con todos los datos."""
    try:
        return send_file(DB_PATH, as_attachment=True, download_name="aula.db")
    except Exception:
        return jsonify({"ok": False, "error": "aun no hay base de datos"}), 404


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)