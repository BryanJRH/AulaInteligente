import os
from collections import deque
from datetime import datetime

from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Clave secreta: debe coincidir con TOKEN_WEB del ESP32.
# Se configura en Railway como variable de entorno llamada SECRETO.
SECRETO = os.environ.get("SECRETO", "")

# Cuantas lecturas se guardan en memoria (historial para la grafica)
MAX_LECTURAS = 500
lecturas = deque(maxlen=MAX_LECTURAS)


def hora_actual():
    return datetime.now().astimezone()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/datos", methods=["POST"])
def recibir_datos():
    """El ESP32 manda aqui la lectura actual."""
    datos = request.get_json(silent=True) or {}

    # Si hay clave configurada, se exige que coincida
    if SECRETO and datos.get("clave") != SECRETO:
        return jsonify({"ok": False, "error": "clave invalida"}), 401

    ahora = hora_actual()
    lectura = {
        "temp": datos.get("temp"),
        "hum": datos.get("hum"),
        "co2": datos.get("co2"),
        "intake": datos.get("intake"),
        "extractor": datos.get("extractor"),
        "hora": ahora.isoformat(timespec="seconds"),
        "ts": ahora.timestamp(),
    }
    lecturas.append(lectura)
    return jsonify({"ok": True}), 201


@app.route("/api/datos", methods=["GET"])
def entregar_datos():
    """La pagina web pide aqui los datos para actualizarse."""
    lista = list(lecturas)
    return jsonify({
        "ultima": lista[-1] if lista else None,
        "historial": lista[-120:],
    })


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)
