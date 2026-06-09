import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# 1. Configuración de Credenciales
USUARIO = os.environ.get("LEVEL_USER")
PASSWORD = os.environ.get("LEVEL_PASS")

# 2. Configuración de la Búsqueda
SEDE_ID = "b9aa2349-3fa8-4679-a761-5df8faa4f612" # ID de AC Este
ACTIVIDAD_DESEADA = "PILATES"
HORARIO_DESEADO = "18:00"

def sacar_turno():
    # DISFRAZ PARA EVITAR EL BLOQUEO DE CLOUDFLARE
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "es-AR,es-419;q=0.9,es;q=0.8,en;q=0.7",
        "Referer": "https://levelmendoza.misactividades.com/"
    }

    session = requests.Session()
    session.headers.update(headers)
    
    # --- FASE 1: LOGIN ---
    print("Iniciando Fase 1: Login...")
    login_url = "https://levelmendoza.misactividades.com/account/login"
    
    res_get_login = session.get(login_url)
    soup_login = BeautifulSoup(res_get_login.text, 'html.parser')
    token_input = soup_login.find('input', {'name': '__RequestVerificationToken'})
    
    if not token_input:
        print("Error crítico: No se encontró el token CSRF inicial.")
        print(f"Estado de la página: {res_get_login.status_code}")
        print("Esto devolvió el servidor en lugar de la página:")
        # Imprimimos los primeros 300 caracteres para ver si es un bloqueo de Cloudflare
        print(res_get_login.text[:300]) 
        return
        
    token_login = token_input['value']
    print("Token obtenido con éxito. Enviando credenciales...")
    
    payload_login = {
        "Email": USUARIO,
        "Password": PASSWORD,
        "__RequestVerificationToken": token_login
    }
    
    res_post_login = session.post(login_url, data=payload_login)
    
    if "Entrenamiento" in res_post_login.text or res_post_login.status_code == 200:
        print("Login exitoso. Avanzando a la Fase 2.")
    else:
        print("Error: Falló el inicio de sesión. Verifica tus credenciales.")
        return

    # --- FASE 2: BUSCAR LA CLASE ---
    print("Iniciando Fase 2: Buscando clase en el calendario...")
    
    fecha_reserva = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"Buscando clases para la fecha: {fecha_reserva}")
    
    calendario_url = f"https://levelmendoza.misactividades.com/bookings/getbookings?branchId={SEDE_ID}&date={fecha_reserva}&instanceCode="
    
    res_calendario = session.get(calendario_url)
    soup_calendario = BeautifulSoup(res_calendario.text, 'html.parser')
    
    clases = soup_calendario.find_all('div', class_='booking-by-date')
    
    class_id_encontrado = None
    
    for clase in clases:
        actividad = clase.get('data-activity')
        hora = clase.get('data-time')
        
        if actividad == ACTIVIDAD_DESEADA and hora == HORARIO_DESEADO:
            onclick_text = clase.get('onclick', '')
            partes = onclick_text.split("'")
            if len(partes) > 1:
                class_id_encontrado = partes[1]
                print(f"¡Clase encontrada! ID dinámico: {class_id_encontrado}")
                break

    if not class_id_encontrado:
        print(f"Error: No se encontró la clase de {ACTIVIDAD_DESEADA} a las {HORARIO_DESEADO} para el día {fecha_reserva}.")
        return

    # --- FASE 3: LA RESERVA FINAL ---
    print("Iniciando Fase 3: Procesando la reserva...")
    
    detalle_url = f"https://levelmendoza.misactividades.com/bookings/getbookingbydate?classId={class_id_encontrado}&isBooking=true"
    res_detalle = session.get(detalle_url)
    soup_detalle = BeautifulSoup(res_detalle.text, 'html.parser')
    
    token_reserva_input = soup_detalle.find('input', {'name': '__RequestVerificationToken'})
    if not token_reserva_input:
        print("No se pudo obtener el token final para la reserva. Abortando.")
        return
        
    token_reserva = token_reserva_input['value']
    
    reserva_url = "https://levelmendoza.misactividades.com/bookings/create"
    
    payload_reserva = {
        "classId": class_id_encontrado,
        "slotNumber": "",
        "instanceCode": "",
        "__RequestVerificationToken": token_reserva
    }
    
    res_final = session.post(reserva_url, data=payload_reserva)
    
    if res_final.status_code == 200:
        print("¡OPERACIÓN EXITOSA! Tu turno para Pilates ha sido reservado.")
    else:
        print(f"Ocurrió un problema al reservar. Código de error: {res_final.status_code}")

if __name__ == "__main__":
    sacar_turno()
