from datetime import date, datetime, timedelta
from flask import (
    Blueprint, render_template, redirect, url_for,
    session, flash, request
)
from database import get_db

main = Blueprint("main", __name__)


def usuario_actual():
    if "usuario_id" not in session:
        return None

    return get_db().execute(
        "SELECT * FROM usuarios WHERE id = ?",
        (session["usuario_id"],)
    ).fetchone()


def requiere_login():
    usuario = usuario_actual()

    if usuario is None:
        flash("Inicia sesión para entrar.", "error")
        return None

    return usuario


def calcular_racha(usuario_id):
    db = get_db()

    fechas = db.execute("""
        SELECT DISTINCT fecha FROM asistencia
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    """, (usuario_id,)).fetchall()

    dias = {fila["fecha"] for fila in fechas}
    actual = date.today()

    if actual.isoformat() not in dias:
        actual -= timedelta(days=1)

    racha = 0

    while actual.isoformat() in dias:
        racha += 1
        actual -= timedelta(days=1)

    return racha


def actualizar_retos(usuario_id):
    db = get_db()

    retos = db.execute(
        "SELECT * FROM retos WHERE activo = 1"
    ).fetchall()

    dias = db.execute("""
        SELECT COUNT(DISTINCT fecha) AS total
        FROM asistencia WHERE usuario_id = ?
    """, (usuario_id,)).fetchone()["total"]

    actividades = db.execute("""
        SELECT COUNT(*) AS total
        FROM asistencia WHERE usuario_id = ?
    """, (usuario_id,)).fetchone()["total"]

    espacios = db.execute("""
        SELECT COUNT(DISTINCT cancha_id) AS total
        FROM reservas
        WHERE usuario_id = ? AND estado = 'confirmada'
    """, (usuario_id,)).fetchone()["total"]

    for reto in retos:
        if "Primeros pasos" in reto["titulo"]:
            progreso = actividades
        elif "Semana activa" in reto["titulo"]:
            progreso = dias
        elif "En movimiento" in reto["titulo"]:
            progreso = actividades
        elif "Explora Tepalcates" in reto["titulo"]:
            progreso = espacios
        else:
            progreso = 0

        progreso = min(progreso, reto["meta"])

        anterior = db.execute("""
            SELECT * FROM usuario_retos
            WHERE usuario_id = ? AND reto_id = ?
        """, (usuario_id, reto["id"])).fetchone()

        if anterior is None:
            db.execute("""
                INSERT INTO usuario_retos
                (usuario_id, reto_id, progreso, completado)
                VALUES (?, ?, ?, ?)
            """, (
                usuario_id, reto["id"], progreso,
                int(progreso >= reto["meta"])
            ))

        else:
            db.execute("""
                UPDATE usuario_retos
                SET progreso = ?, completado = ?
                WHERE usuario_id = ? AND reto_id = ?
            """, (
                progreso, int(progreso >= reto["meta"]),
                usuario_id, reto["id"]
            ))

    db.commit()


@main.route("/")
def index():
    return render_template("index.html")


@main.route("/dashboard")
def dashboard():
    usuario = requiere_login()

    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    puntos = db.execute("""
        SELECT COALESCE(SUM(puntos), 0) AS total
        FROM asistencia WHERE usuario_id = ?
    """, (usuario["id"],)).fetchone()["total"]

    racha = calcular_racha(usuario["id"])

    reservas = db.execute("""
        SELECT COUNT(*) AS total FROM reservas
        WHERE usuario_id = ? AND estado = 'confirmada'
    """, (usuario["id"],)).fetchone()["total"]

    actualizar_retos(usuario["id"])

    return render_template(
        "dashboard.html",
        usuario=usuario,
        puntos=puntos,
        racha=racha,
        reservas=reservas
    )


@main.route("/seccion/<slug>")
def seccion(slug):
    rutas = {
        "canchas": "canchas",
        "reservas": "reservas",
        "calendario": "calendario",
        "mapa": "mapa",
        "retos": "retos",
        "posiciones": "posiciones",
        "actividad": "actividad",
        "eventos": "eventos",
        "avisos": "avisos",
        "reportes": "reportes",
        "comunidad": "comunidad",
        "rachas": "rachas"
    }

    if slug not in rutas:
        return redirect(url_for("main.dashboard"))

    return redirect(url_for(f"main.{rutas[slug]}"))


@main.route("/canchas")
def canchas():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    espacios = get_db().execute(
        "SELECT * FROM canchas WHERE disponible = 1"
    ).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Canchas y espacios",
        tipo="canchas",
        elementos=espacios
    )


@main.route("/reservas", methods=["GET", "POST"])
def reservas():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":
        cancha_id = request.form.get("cancha_id", type=int)
        fecha = request.form.get("fecha", "")
        inicio = request.form.get("hora_inicio", "")
        fin = request.form.get("hora_fin", "")

        try:
            dia = date.fromisoformat(fecha)
            hora_inicio = datetime.strptime(inicio, "%H:%M").time()
            hora_fin = datetime.strptime(fin, "%H:%M").time()
        except ValueError:
            flash("Revisa la fecha y las horas.", "error")
            return redirect(url_for("main.reservas"))

        cancha = db.execute(
            "SELECT * FROM canchas WHERE id = ? AND disponible = 1",
            (cancha_id,)
        ).fetchone()

        if not cancha or dia < date.today():
            flash("La cancha o fecha no es válida.", "error")
            return redirect(url_for("main.reservas"))

        if hora_inicio >= hora_fin:
            flash("La hora final debe ser posterior a la inicial.", "error")
            return redirect(url_for("main.reservas"))

        if hora_inicio.hour < 7 or hora_fin.hour > 21:
            flash("Las reservas deben ser entre 7:00 y 21:00.", "error")
            return redirect(url_for("main.reservas"))

        conflicto = db.execute("""
            SELECT id FROM reservas
            WHERE cancha_id = ?
            AND fecha = ?
            AND estado = 'confirmada'
            AND hora_inicio < ?
            AND hora_fin > ?
        """, (cancha_id, fecha, fin, inicio)).fetchone()

        if conflicto:
            flash("Ese horario ya está reservado.", "error")
            return redirect(url_for("main.reservas"))

        db.execute("""
            INSERT INTO reservas
            (usuario_id, cancha_id, fecha, hora_inicio, hora_fin)
            VALUES (?, ?, ?, ?, ?)
        """, (usuario["id"], cancha_id, fecha, inicio, fin))

        db.commit()
        flash("¡Tu reserva quedó registrada!", "success")
        return redirect(url_for("main.reservas"))

    espacios = db.execute(
        "SELECT * FROM canchas WHERE disponible = 1"
    ).fetchall()

    mis_reservas = db.execute("""
        SELECT reservas.*, canchas.nombre AS cancha
        FROM reservas
        JOIN canchas ON canchas.id = reservas.cancha_id
        WHERE reservas.usuario_id = ?
        ORDER BY fecha DESC, hora_inicio DESC
    """, (usuario["id"],)).fetchall()

    return render_template(
        "reservas.html",
        usuario=usuario,
        canchas=espacios,
        reservas=mis_reservas,
        hoy=date.today().isoformat()
    )


@main.route("/reservas/cancelar/<int:reserva_id>", methods=["POST"])
def cancelar_reserva(reserva_id):
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    db.execute("""
        UPDATE reservas SET estado = 'cancelada'
        WHERE id = ? AND usuario_id = ?
    """, (reserva_id, usuario["id"]))

    db.commit()
    flash("Reserva cancelada.", "success")
    return redirect(url_for("main.reservas"))


@main.route("/rachas", methods=["GET", "POST"])
def rachas():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":
        try:
            cursor = db.execute("""
                INSERT OR IGNORE INTO asistencia
                (usuario_id, fecha, actividad, puntos)
                VALUES (?, ?, ?, ?)
            """, (
                usuario["id"],
                date.today().isoformat(),
                request.form.get("actividad", "Actividad deportiva"),
                10
            ))
            db.commit()

            if cursor.rowcount:
                flash("¡Actividad registrada! Ganaste 10 puntos.", "success")
            else:
                flash("Ya registraste tu actividad de hoy.", "error")

        except Exception:
            flash("No se pudo registrar la actividad.", "error")

        return redirect(url_for("main.rachas"))

    historial = db.execute("""
        SELECT * FROM asistencia
        WHERE usuario_id = ?
        ORDER BY fecha DESC
        LIMIT 30
    """, (usuario["id"],)).fetchall()

    racha = calcular_racha(usuario["id"])

    puntos = db.execute("""
        SELECT COALESCE(SUM(puntos), 0) AS total
        FROM asistencia WHERE usuario_id = ?
    """, (usuario["id"],)).fetchone()["total"]

    actualizar_retos(usuario["id"])

    return render_template(
        "rachas.html",
        usuario=usuario,
        historial=historial,
        racha=racha,
        puntos=puntos
    )


@main.route("/retos")
def retos():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    actualizar_retos(usuario["id"])
    db = get_db()

    lista = db.execute("""
        SELECT retos.*, usuario_retos.progreso,
        usuario_retos.completado
        FROM retos
        LEFT JOIN usuario_retos
        ON retos.id = usuario_retos.reto_id
        AND usuario_retos.usuario_id = ?
        WHERE retos.activo = 1
    """, (usuario["id"],)).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Retos deportivos",
        tipo="retos",
        elementos=lista
    )


@main.route("/posiciones")
def posiciones():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    tabla = get_db().execute("""
        SELECT usuarios.nombre,
        COALESCE(SUM(asistencia.puntos), 0) AS puntos
        FROM usuarios
        LEFT JOIN asistencia ON usuarios.id = asistencia.usuario_id
        GROUP BY usuarios.id
        ORDER BY puntos DESC, usuarios.nombre ASC
    """).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Tabla de posiciones",
        tipo="posiciones",
        elementos=tabla
    )


@main.route("/actividad")
def actividad():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    datos = get_db().execute("""
        SELECT * FROM asistencia
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    """, (usuario["id"],)).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Mi actividad",
        tipo="actividad",
        elementos=datos
    )


@main.route("/calendario")
def calendario():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    eventos = get_db().execute("""
        SELECT * FROM actividades
        WHERE estado = 'activo'
        ORDER BY fecha, hora
    """).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Calendario deportivo",
        tipo="calendario",
        elementos=eventos
    )


@main.route("/eventos")
def eventos():
    return redirect(url_for("main.calendario"))


@main.route("/mapa")
def mapa():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    espacios = get_db().execute(
        "SELECT * FROM canchas"
    ).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Mapa del deportivo",
        tipo="mapa",
        elementos=espacios
    )


@main.route("/avisos")
def avisos():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    lista = get_db().execute("""
        SELECT * FROM avisos WHERE activo = 1
        ORDER BY fecha DESC
    """).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Avisos importantes",
        tipo="avisos",
        elementos=lista
    )


@main.route("/reportes", methods=["GET", "POST"])
def reportes():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":
        asunto = request.form.get("asunto", "").strip()
        mensaje = request.form.get("mensaje", "").strip()

        if asunto and mensaje:
            db.execute("""
                INSERT INTO reportes (usuario_id, asunto, mensaje)
                VALUES (?, ?, ?)
            """, (usuario["id"], asunto, mensaje))
            db.commit()
            flash("Tu reporte fue enviado.", "success")
            return redirect(url_for("main.reportes"))

        flash("Completa todos los campos.", "error")

    lista = db.execute("""
        SELECT * FROM reportes
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    """, (usuario["id"],)).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Reportes y sugerencias",
        tipo="reportes",
        elementos=lista
    )


@main.route("/comunidad", methods=["GET", "POST"])
def comunidad():
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))

    db = get_db()

    if request.method == "POST":
        mensaje = request.form.get("mensaje", "").strip()

        if mensaje:
            db.execute("""
                INSERT INTO testimonios (usuario_id, mensaje)
                VALUES (?, ?)
            """, (usuario["id"], mensaje))
            db.commit()
            flash("Tu publicación fue compartida.", "success")
            return redirect(url_for("main.comunidad"))

    publicaciones = db.execute("""
        SELECT testimonios.*, usuarios.nombre
        FROM testimonios
        JOIN usuarios ON usuarios.id = testimonios.usuario_id
        ORDER BY testimonios.fecha DESC
    """).fetchall()

    return render_template(
        "seccion.html",
        usuario=usuario,
        titulo="Comunidad",
        tipo="comunidad",
        elementos=publicaciones
    )
    # --- DETALLE DE CADA ESPACIO DEL TEPALCATES ---
INFO_ESPACIOS = {
    "Fútbol": {
        "descripcion": "Cancha de fútbol 7 de pasto sintético, ideal para retas y torneos de la comunidad.",
        "ubicacion": "Deportivo Tepalcates, Chimalhuacán, Edo. de México",
        "horario": "Lunes a Domingo 8:00 am a 8:00 pm",
        "superficie": "Pasto sintético",
        "capacidad": "14 jugadores",
        "servicios": "Baños, Gradas, Iluminación nocturna, Estacionamiento",
        "reglas": "Usar tenis, no entrar con tacos de metal. Apartar con 1 día de anticipación.",
        "foto": "img/tepalcates-futbol.jpg"
    },
    "Básquetbol": {
        "descripcion": "Cancha techada con tableros profesionales para entrenar y jugar cascaritas.",
        "ubicacion": "Deportivo Tepalcates, Chimalhuacán",
        "horario": "Lunes a Domingo 8:00 am a 8:00 pm",
        "superficie": "Concreto pintado",
        "capacidad": "10 jugadores",
        "servicios": "Techada, Baños, Bancas",
        "reglas": "No colgarse del aro. Respetar turnos de juego.",
        "foto": "img/tepalcates-basquet.jpg"
    },
    "Voleibol": {
        "descripcion": "Cancha de voleibol con red y líneas marcadas.",
        "ubicacion": "Deportivo Tepalcates, Chimalhuacán",
        "horario": "Lunes a Domingo 9:00 am a 7:00 pm",
        "superficie": "Concreto",
        "capacidad": "12 jugadores",
        "servicios": "Red, Baños, Gradas",
        "reglas": "Traer tu propio balón si puedes.",
        "foto": "img/tepalcates-volei.jpg"
    },
}

@main.route("/cancha/<int:cancha_id>")
def detalle_cancha(cancha_id):
    usuario = requiere_login()
    if usuario is None:
        return redirect(url_for("auth.login"))
    db = get_db()
    cancha = db.execute(
        "SELECT * FROM canchas WHERE id = ? AND disponible = 1",
        (cancha_id,)
    ).fetchone()
    if not cancha:
        return "Espacio no encontrado", 404
    extra = INFO_ESPACIOS.get(cancha["deporte"], {
        "descripcion": "Espacio deportivo del Deportivo Tepalcates.",
        "ubicacion": "Deportivo Tepalcates, Chimalhuacán",
        "horario": "Lunes a Domingo 8:00 am a 8:00 pm",
        "superficie": "Aire libre",
        "capacidad": "Variable",
        "servicios": "Baños, Bancas",
        "reglas": "Cuidar las instalaciones, no dejar basura.",
        "foto": "img/tepalcates-general.jpg"
    })
    return render_template("detalle_cancha.html", cancha=cancha, extra=extra)
