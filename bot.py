import os
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 1. Configuración de Credenciales
USUARIO = os.environ.get("LEVEL_USER")
PASSWORD = os.environ.get("LEVEL_PASS")

# 2. Configuración de la Búsqueda
SEDE_ID = "b9aa2349-3fa8-4679-a761-5df8faa4f612"  # ID de AC Este
ACTIVIDAD_DESEADA = "PILATES"
HORARIO_DESEADO = "18:00"

TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")
HORA_APERTURA = "19:00:00"  # hora argentina en que se habilita el turno (23hs antes de la clase)


def esperar_hasta_arg(hora_str: str):
    """Duerme con precisión hasta que sea exactamente hora_str en horario argentino."""
    h, m, s = map(int, hora_str.split(":"))
    ahora = datetime.now(TZ_ARG)
    objetivo = ahora.replace(hour=h, minute=m, second=s, microsecond=0)
    if objetivo <= ahora:
        objetivo += timedelta(days=1)

    restante = (objetivo - datetime.now(TZ_ARG)).total_seconds()
    print(f"Faltan {restante:.1f}s para las {hora_str} ARG. Durmiendo grueso...")

    # Dormir en bloques hasta quedar cerca (deja 1.5s de margen para el spin final)
    while restante > 1.5:
        time.sleep(min(restante - 1.5, 5))
        restante = (objetivo - datetime.now(TZ_ARG)).total_seconds()

    # Espera activa (spin) para los últimos milisegundos: más preciso que sleep()
    while datetime.now(TZ_ARG) < objetivo:
        pass

    print(f"¡Hora exacta alcanzada! ({datetime.now(TZ_ARG).strftime('%H:%M:%S.%f')})")


def login(session, headers):
    print("Iniciando Fase 1: Login...")
    login_url = "https://levelmendoza.misactividades.com/account/login"

    res_get_login = session.get(login_url)
    soup_login = BeautifulSoup(res_get_login.text, 'html.parser')
    token_input = soup_login.find('input', {'name': '__RequestVerificationToken'})

    if not token_input:
        print("Error crítico: No se encontró el token CSRF inicial.")
        print(f"Estado de la página: {res_get_login.status_code}")
        print(res_get_login.text[:300])
        return False

    token_login = token_input['value']
    print("Token obtenido con éxito. Enviando credenciales...")

    payload_login = {
        "Email": USUARIO,
        "Password": PASSWORD,
        "__RequestVerificationToken": token_login
    }

    res_post_login = session.post(login_url, data=payload_login)

    if "Entrenamiento" in res_post_login.text or res_post_login.status_code == 200:
        print("Login exitoso.")
        return True

    print("Error: Falló el inicio de sesión. Verifica tus credenciales.")
    return False


def buscar_clase(session):
    print("Iniciando Fase 2: Buscando clase en el calendario...")

    fecha_reserva = (datetime.now(TZ_ARG) + timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"Buscando clases para la fecha: {fecha_reserva}")

    calendario_url = (
        f"https://levelmendoza.misactividades.com/bookings/getbookings"
        f"?branchId={SEDE_ID}&date={fecha_reserva}&instanceCode="
    )

    res_calendario = session.get(calendario_url)
    soup_calendario = BeautifulSoup(res_calendario.text, 'html.parser')

    clases = soup_calendario.find_all('div', class_='booking-by-date')

    for clase in clases:
        actividad = clase.get('data-activity')
        hora = clase.get('data-time')

        if actividad == ACTIVIDAD_DESEADA and hora == HORARIO_DESEADO:
            onclick_text = clase.get('onclick', '')
            partes = onclick_text.split("'")
            if len(partes) > 1:
                class_id = partes[1]
                print(f"¡Clase encontrada! ID dinámico: {class_id}")
                return class_id

    print(f"No se encontró la clase de {ACTIVIDAD_DESEADA} a las {HORARIO_DESEADO} para el {fecha_reserva}.")
    return None


def obtener_token_reserva(session, class_id):
    """Pide el token de reserva ANTES de la hora de apertura, para no perder tiempo justo al momento crítico."""
    detalle_url = (
        f"https://levelmendoza.misactividades.com/bookings/getbookingbydate"
        f"?classId={class_id}&isBooking=true"
    )
    res_detalle = session.get(detalle_url)
    soup_detalle = BeautifulSoup(res_detalle.text, 'html.parser')

    token_input = soup_detalle.find('input', {'name': '__RequestVerificationToken'})
    if not token_input:
        print("No se pudo obtener el token de reserva.")
        return None

    return token_input['value']


def reservar_una_vez(session, class_id, token):
    reserva_url = "https://levelmendoza.misactividades.com/bookings/create"

    payload_reserva = {
        "classId": class_id,
        "slotNumber": "",
        "instanceCode": "",
        "__RequestVerificationToken": token
    }

    res_final = session.post(reserva_url, data=payload_reserva)
    return res_final


def reservar_con_reintentos(session, class_id, max_intentos=5, espera_entre_intentos=0.6):
    """
    Intenta reservar varias veces seguidas. Antes de cada intento pide un token
    fresco (por si el anterior venció o quedó invalidado por un intento previo).
    Se corta apenas hay éxito, o si el servidor indica explícitamente que el
    cupo ya está completo (para no seguir insistiendo en vano).
    """
    for intento in range(1, max_intentos + 1):
        print(f"Fase 3: Intento de reserva #{intento}...")

        token = obtener_token_reserva(session, class_id)
        if not token:
            print("No se pudo obtener token en este intento, reintentando...")
            time.sleep(espera_entre_intentos)
            continue

        res_final = reservar_una_vez(session, class_id, token)
        cuerpo = res_final.text[:300]

        if res_final.status_code == 200 and "error" not in cuerpo.lower():
            print("¡OPERACIÓN EXITOSA! Tu turno para Pilates ha sido reservado.")
            return True

        # Detectar cupo lleno explícitamente para no seguir gastando intentos
        texto_lower = cuerpo.lower()
        if "completo" in texto_lower or "lleno" in texto_lower or "sin cupo" in texto_lower:
            print("El cupo ya está lleno. No tiene sentido seguir reintentando.")
            print(cuerpo)
            return False

        print(f"Intento #{intento} falló. Código: {res_final.status_code}")
        print(cuerpo)

        if intento < max_intentos:
            time.sleep(espera_entre_intentos)

    print(f"Se agotaron los {max_intentos} intentos sin éxito.")
    return False


def sacar_turno():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "es-AR,es-419;q=0.9,es;q=0.8,en;q=0.7",
        "Referer": "https://levelmendoza.misactividades.com/"
    }

    session = requests.Session()
    session.headers.update(headers)

    # --- Precalentamiento: todo esto se hace ANTES de la hora, sin apuro ---
    if not login(session, headers):
        return

    class_id = buscar_clase(session)
    if not class_id:
        return

    # --- Espera de precisión hasta las 19:00:00 ARG ---
    esperar_hasta_arg(HORA_APERTURA)

    # --- A partir de acá, cada milisegundo cuenta ---
    reservar_con_reintentos(session, class_id, max_intentos=5, espera_entre_intentos=0.6)


if __name__ == "__main__":
    sacar_turno()
