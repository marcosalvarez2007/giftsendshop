import os, requests, json, base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict

# Compiled Protos
import GetGiftStoreDetails_pb2
import GetWallet_pb2
import SendGift_pb2

load_dotenv()
IMAGE_BASE_URL = "https://star-icon-png.lovable.app/png?icon_id="
JWT_GEN_API = "https://ff-jwt-gen-api.lovable.app/api/public/token"

app = Flask(__name__)

# --- CONFIG ---
KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
USER_AGENT = "UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"

PREFIX_MAP = {
    "902": "Avatar", "214": "Pintura facial", "101": "Habilidades femeninas", "102": "Habilidades masculinas",
    "103": "Microchip", "905": "Paracaídas", "710": "Paquete", "720": "Paquete 2",
    "203": "Parte superior", "204": "Parte inferior", "205": "Zapatos", "211": "Cabeza", "901": "Estandarte",
    "131": "Mascota 2", "130": "Mascotas / Gestos", "903": "Caja de botín", "904": "Mochila",
    "906": "Tabla aérea", "907": "Otros", "908": "Vehículos", "909": "Gesto",
    "911": "Alas celestes", "922": "Aspecto de habilidad",
}

STORE_CACHE = {}
MAX_GIFT_QUANTITY = 999
FEATURED_ITEMS = {
    '803000000': 'Pase Booyah',
    '400046114': 'Caja de Tokens Evo Universal',
    '400044555': 'Caja de Tokens Universales de Arma Evo',
    '801039059': 'Token Universal de Arma Evo',
    '817000001': 'Fragmento Universal',
    '400037169': 'Caja Fragmento Evo',
}

def encrypt_payload(data):
    cipher = AES.new(KEY, AES.MODE_CBC, IV)
    return cipher.encrypt(pad(data, AES.block_size))

def get_server_url(region):
    if region == "IND": return "https://client.ind.freefiremobile.com"
    elif region in ["BR", "US", "SAC", "NA"]: return "https://client.us.freefiremobile.com"
    else: return "https://clientbp.ggpolarbear.com"

def decode_jwt(token):
    try:
        if not isinstance(token, str):
            return None, None
        parts = token.split('.')
        if len(parts) != 3:
            return None, None
        payload_part = parts[1]
        payload_part += '=' * (-len(payload_part) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload_part.encode('ascii')))
        if not isinstance(decoded, dict):
            return None, None
        return decoded.get("lock_region"), decoded.get("external_id")
    except (ValueError, TypeError, UnicodeError):
        return None, None


def decode_account_profile(token):
    try:
        payload_part = token.split('.')[1]
        payload_part += '=' * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part.encode('ascii')))
        nested = payload.get('user') or payload.get('account') or {}
        name = next((str(source[key]).strip() for source in (payload, nested) for key in ('nickname', 'player_name', 'account_name', 'name') if source.get(key)), '')
        account_id = payload.get('external_id') or payload.get('account_id') or payload.get('uid') or ''
        return {'account_name': name, 'account_id': str(account_id)}
    except Exception:
        return {'account_name': '', 'account_id': ''}
SPANISH_MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')

def format_spanish_date(timestamp, include_time=False):
    value = datetime.fromtimestamp(timestamp)
    result = f"{value.day} de {SPANISH_MONTHS[value.month - 1]} de {value.year}"
    return f"{result}, {value:%H:%M}" if include_time else result
def get_wallet_data(jwt, login_token, region):
    req = GetWallet_pb2.CSGetWalletReq(login_token=login_token, topup_rebate=False)
    headers = {"Authorization": f"Bearer {jwt}", "X-GA": "v1 1", "ReleaseVersion": "OB55", "Content-Type": "application/octet-stream", "User-Agent": USER_AGENT}
    try:
        r = requests.post(f"{get_server_url(region)}/GetWallet", data=encrypt_payload(req.SerializeToString()), headers=headers, timeout=10)
        if r.status_code == 200:
            res_pb = GetWallet_pb2.CSGetWalletRes()
            res_pb.ParseFromString(r.content)
            w = res_pb.wallet
            ts = format_spanish_date(w.last_topup_time, include_time=True) if w.last_topup_time > 0 else "Nunca"
            return {"gold": w.coins, "diamond": w.gems, "last_topup": ts}
    except: pass
    return {"gold": 0, "diamond": 0, "last_topup": "Error"}

@app.route('/')
def index():
    return HTML_INDEX

@app.route('/api/generate_jwt', methods=['POST'])
def generate_jwt():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Solicitud inválida"}), 400
    access_token = data.get('access_token')
    if not access_token:
        return jsonify({"success": False, "message": "Se requiere un token de acceso"}), 400
    
    try:
        response = requests.get(JWT_GEN_API, params={"access_token": access_token}, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get('success') and result.get('token'):
                return jsonify({"success": True, "jwt": result['token']})
            else:
                return jsonify({"success": False, "message": result.get('message', 'No se pudo generar el JWT')}), 400
        else:
            return jsonify({"success": False, "message": f"Error de API: {response.status_code}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/image/<item_id>')
def serve_image(item_id):
    if not item_id.isdigit() or len(item_id) > 15:
        return "Not Found", 404
    try:
        response = requests.get(f"{IMAGE_BASE_URL}{item_id}", timeout=5)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').split(';', 1)[0]
        if not content_type.startswith('image/'):
            return "Not Found", 404
        return Response(response.content, mimetype=content_type)
    except requests.RequestException:
        return "Not Found", 404

@app.route('/api/get_store', methods=['POST'])
def get_store():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Solicitud inválida"}), 400
    jwt_token = data.get('jwt')
    try:
        page = max(1, int(data.get('page', 1)))
        limit = min(48, max(1, int(data.get('limit', 24))))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Paginación inválida"}), 400
    cat = data.get('category', 'All')
    region, login_token = decode_jwt(jwt_token)
    account_profile = decode_account_profile(jwt_token)
    if not region: return jsonify({"success": False, "message": "¡JWT inválido!"}), 400

    if jwt_token not in STORE_CACHE:
        wallet = get_wallet_data(jwt_token, login_token, region)
        req_pb = GetGiftStoreDetails_pb2.CSGetGiftStoreDetailsReq(store_id=1)
        headers = {"Authorization": f"Bearer {jwt_token}", "X-GA": "v1 1", "ReleaseVersion": "OB55", "Content-Type": "application/octet-stream", "User-Agent": USER_AGENT}
        
        try:
            r = requests.post(f"{get_server_url(region)}/GetGiftStoreDetails", data=encrypt_payload(req_pb.SerializeToString()), headers=headers, timeout=15)
            if r.status_code == 200:
                res_pb = GetGiftStoreDetails_pb2.CSGetGiftStoreDetailsRes()
                res_pb.ParseFromString(r.content)
                res_dict = MessageToDict(res_pb, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
                
                all_items, categories = [], set()
                for item in res_dict.get('items', []):
                    item_id_str = str(item.get('item_id', '0'))
                    c_name = PREFIX_MAP.get(item_id_str[:3], f"Otro ({item_id_str[:3]})")
                    categories.add(c_name)
                    
                    g, c = int(item.get('gems_price', 0)), int(item.get('coins_price', 0))
                    price = f"💎 {g} / 🪙 {c}" if g>0 and c>0 else f"💎 {g}" if g>0 else f"🪙 {c}" if c>0 else "Gratis"
                    
                    ts = int(item.get('expire_timestamp', 0))
                    exp_date = format_spanish_date(ts) if ts > 0 else "Permanente"
                    featured_name = FEATURED_ITEMS.get(item_id_str, '')
                    all_items.append({
                        "item_id": item_id_str, "commodity_id": item.get('commodity_id'),
                        "sort_id": int(item.get('sort_id', 0)), "price_str": price,
                        "gems_price": g, "coins_price": c,
                        "category": c_name, "expire_date": exp_date,
                        "featured_name": featured_name
                    })

                all_items.sort(key=lambda x: (bool(x['featured_name']), x['sort_id']), reverse=True)
                STORE_CACHE[jwt_token] = {'items': all_items, 'wallet': wallet, 'sent': res_dict.get('send_gift_times_today', 0), 'cats': sorted(list(categories))}
            else: return jsonify({"success": False, "message": "Error de Garena"}), 400
        except Exception as e: return jsonify({"success": False, "message": str(e)}), 500

    cache = STORE_CACHE[jwt_token]
    if cat == 'Featured':
        filtered = [x for x in cache['items'] if x.get('featured_name')]
    elif cat != 'All':
        filtered = [x for x in cache['items'] if x['category'] == cat]
    else:
        filtered = cache['items']
    start = (page - 1) * limit
    
    return jsonify({
        "success": True, "items": filtered[start : start + limit], 
        "categories": cache['cats'], "wallet": cache['wallet'], 
        "sent_today": cache['sent'], "account_name": account_profile['account_name'], "account_id": account_profile['account_id'], "has_more": (start + limit) < len(filtered)
    })

@app.route('/api/send_gift', methods=['POST'])
def send_gift():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Solicitud inválida"}), 400
    jwt = data.get('jwt')
    if not isinstance(jwt, str) or not jwt:
        return jsonify({"success": False, "message": "JWT inválido"}), 400

    try:
        receiver_uid = int(str(data.get('receiver_uid', '')).strip())
        commodity_id = int(str(data.get('commodity_id', '')).strip())
        quantity = int(str(data.get('quantity', '1')).strip())
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "UID, artículo o cantidad inválidos"}), 400

    if receiver_uid <= 0 or receiver_uid > (2**64 - 1):
        return jsonify({"success": False, "message": "El UID debe ser un número válido"}), 400
    if commodity_id <= 0 or commodity_id > (2**32 - 1):
        return jsonify({"success": False, "message": "El identificador del artículo no es válido"}), 400
    if quantity < 1 or quantity > MAX_GIFT_QUANTITY:
        return jsonify({"success": False, "message": f"La cantidad debe estar entre 1 y {MAX_GIFT_QUANTITY}"}), 400

    region, _ = decode_jwt(jwt)
    if not region:
        return jsonify({"success": False, "message": "JWT inválido"}), 400

    cached_store = STORE_CACHE.get(jwt)
    if not cached_store:
        return jsonify({"success": False, "message": "Carga el catálogo antes de enviar un regalo"}), 400
    item = next((entry for entry in cached_store['items'] if str(entry.get('commodity_id')) == str(commodity_id)), None)
    if not item:
        return jsonify({"success": False, "message": "El artículo no está disponible en el catálogo cargado"}), 400

    currency = data.get('currency')
    if currency == 'diamond':
        unit_price = int(item.get('gems_price', 0))
        currency_type = 2
    elif currency == 'gold':
        unit_price = int(item.get('coins_price', 0))
        currency_type = 1
    else:
        return jsonify({"success": False, "message": "Moneda inválida"}), 400
    if unit_price <= 0 or unit_price > (2**32 - 1):
        return jsonify({"success": False, "message": "El precio del artículo no es válido para esa moneda"}), 400

    message = data.get('message', '¡Disfruta tu regalo! 🎉')
    if not isinstance(message, str):
        message = '¡Disfruta tu regalo! 🎉'
    message = message.strip()[:120] or '¡Disfruta tu regalo! 🎉'

    req = SendGift_pb2.CSSendGiftReq()
    req.receiver_account_ids.append(receiver_uid)
    req.buddy_type = 1
    req.commodity_id = commodity_id
    req.message_content = message
    req.currency_type = currency_type
    req.commodity_cnt = quantity
    req.unit_price = unit_price

    headers = {"Authorization": f"Bearer {jwt}", "X-GA": "v1 1", "ReleaseVersion": "OB55", "Content-Type": "application/octet-stream", "User-Agent": USER_AGENT}

    try:
        r = requests.post(f"{get_server_url(region)}/SendGift", data=encrypt_payload(req.SerializeToString()), headers=headers, timeout=15)
        if r.status_code == 200:
            STORE_CACHE.pop(jwt, None)
            return jsonify({"success": True, "message": f"Regalo enviado a {receiver_uid}", "quantity": quantity})
        return jsonify({"success": False, "message": f"El servidor rechazó el envío (código {r.status_code})"}), 502
    except requests.RequestException:
        return jsonify({"success": False, "message": "No se pudo conectar con el servidor del juego"}), 502

# ===== HTML CONTENT =====
HTML_INDEX = '''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#07110f">
<title>Marcos Dev | Estudio de regalos</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
    --primary: #10b981;
    --primary-dark: #059669;
    --primary-glow: rgba(16, 185, 129, 0.3);
    --bg-dark: #0a0f1a;
    --bg-card: rgba(30, 41, 59, 0.6);
    --border-color: rgba(255,255,255,0.06);
    --text-white: #f8fafc;
    --text-gray: #94a3b8;
    --shadow: 0 20px 60px rgba(0,0,0,0.5);
}
body {
    font-family: 'Inter', sans-serif;
    background: var(--bg-dark);
    color: var(--text-white);
    min-height: 100vh;
    background-image: 
        radial-gradient(ellipse at 10% 20%, rgba(16, 185, 129, 0.08) 0%, transparent 50%),
        radial-gradient(ellipse at 90% 80%, rgba(16, 185, 129, 0.05) 0%, transparent 50%),
        linear-gradient(180deg, #0a0f1a 0%, #0d1520 100%);
    overflow-x: hidden;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); border-radius: 10px; }
::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary-dark); }
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
@keyframes float {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-5px); }
}
@keyframes spin {
    to { transform: rotate(360deg); }
}
@keyframes slideDown {
    from { opacity: 0; transform: translateY(-20px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes scaleIn {
    from { opacity: 0; transform: scale(0.9); }
    to { opacity: 1; transform: scale(1); }
}
.main-header {
    background: rgba(10, 15, 26, 0.8);
    backdrop-filter: blur(20px) saturate(1.5);
    padding: 20px 30px;
    text-align: center;
    border-bottom: 1px solid var(--border-color);
    position: sticky;
    top: 0;
    z-index: 100;
}
.main-header h1 {
    font-size: 2.2em;
    font-weight: 900;
    background: linear-gradient(135deg, #10b981, #34d399, #10b981);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: shimmer 3s linear infinite;
    letter-spacing: -1px;
}
.main-header .subtitle {
    color: var(--text-gray);
    font-size: 0.9em;
    margin-top: 4px;
    letter-spacing: 0.5px;
}
.main-header .subtitle span {
    color: var(--primary);
    -webkit-text-fill-color: var(--primary);
}
.login-container {
    max-width: 480px;
    margin: 60px auto;
    background: var(--bg-card);
    backdrop-filter: blur(20px);
    padding: 45px 40px;
    border-radius: 24px;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow);
    animation: scaleIn 0.6s ease;
    transition: all 0.3s ease;
}
.login-container:hover {
    border-color: rgba(16, 185, 129, 0.2);
}
.login-container .logo-icon {
    font-size: 3em;
    display: block;
    margin-bottom: 10px;
    animation: float 3s ease-in-out infinite;
}
.login-container h2 {
    font-size: 1.5em;
    font-weight: 700;
    color: var(--text-white);
    margin-bottom: 6px;
}
.login-container .login-desc {
    color: var(--text-gray);
    font-size: 0.9em;
    margin-bottom: 25px;
}
.login-container .input-group {
    position: relative;
    margin-bottom: 16px;
}
.login-container .input-group input {
    width: 100%;
    padding: 16px 18px;
    border-radius: 14px;
    border: 2px solid rgba(255,255,255,0.06);
    background: rgba(15, 23, 42, 0.8);
    color: var(--text-white);
    font-size: 0.95em;
    outline: none;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
}
.login-container .input-group input::placeholder {
    color: rgba(148, 163, 184, 0.5);
}
.login-container .input-group input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px var(--primary-glow);
}
.login-container .input-group input.success {
    border-color: var(--primary);
    background: rgba(16, 185, 129, 0.05);
}
.login-container .btn-primary {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: white;
    border: none;
    padding: 16px;
    font-size: 1em;
    font-weight: 700;
    border-radius: 14px;
    cursor: pointer;
    width: 100%;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
    font-family: 'Inter', sans-serif;
}
.login-container .btn-primary:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 8px 30px var(--primary-glow);
}
.login-container .btn-primary:active:not(:disabled) {
    transform: scale(0.98);
}
.login-container .btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
}
.login-container .btn-primary .loader {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
    margin-right: 10px;
}
.login-container .divider {
    display: flex;
    align-items: center;
    gap: 15px;
    margin: 20px 0;
    color: var(--text-gray);
    font-size: 0.8em;
}
.login-container .divider::before,
.login-container .divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border-color);
}
.error-msg {
    color: #ef4444;
    font-size: 0.85em;
    margin-top: 12px;
    display: none;
    padding: 10px 14px;
    background: rgba(239, 68, 68, 0.1);
    border-radius: 10px;
    border: 1px solid rgba(239, 68, 68, 0.2);
}
.error-msg.show { display: block; animation: slideDown 0.3s ease; }
.success-msg {
    color: var(--primary);
    font-size: 0.85em;
    margin-top: 12px;
    display: none;
    padding: 10px 14px;
    background: rgba(16, 185, 129, 0.1);
    border-radius: 10px;
    border: 1px solid rgba(16, 185, 129, 0.2);
}
.success-msg.show { display: block; animation: slideDown 0.3s ease; }
.store-container {
    max-width: 1280px;
    margin: 30px auto;
    padding: 0 24px;
    animation: fadeInUp 0.6s ease;
}
.wallet-bar {
    display: grid;
    grid-template-columns: 1fr 1fr 1.5fr;
    gap: 14px;
    background: var(--bg-card);
    backdrop-filter: blur(20px);
    padding: 18px 24px;
    border-radius: 18px;
    margin-bottom: 25px;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow);
}
.wallet-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    background: rgba(15, 23, 42, 0.6);
    padding: 12px 16px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.04);
    transition: all 0.3s ease;
}
.wallet-item:hover {
    border-color: rgba(16, 185, 129, 0.15);
    transform: translateY(-2px);
}
.wallet-item .label {
    font-size: 0.7em;
    color: var(--text-gray);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    font-weight: 600;
}
.wallet-item .value {
    font-size: 1.3em;
    font-weight: 800;
}
.wallet-item .value.diamond { color: #38bdf8; }
.wallet-item .value.gold { color: #fbbf24; }
.wallet-item .value.topup { color: var(--primary); font-size: 0.9em; }
.store-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 15px;
    margin-bottom: 20px;
}
.store-header h3 {
    font-size: 1.4em;
    font-weight: 700;
    color: var(--text-white);
}
.store-header h3 span {
    color: var(--primary);
}
.store-header .sent-badge {
    background: rgba(16, 185, 129, 0.1);
    padding: 8px 18px;
    border-radius: 50px;
    color: var(--primary);
    font-weight: 600;
    font-size: 0.85em;
    border: 1px solid rgba(16, 185, 129, 0.15);
    display: flex;
    align-items: center;
    gap: 8px;
}
.store-header .sent-badge .count {
    background: var(--primary);
    color: white;
    padding: 0 10px;
    border-radius: 50px;
    font-size: 0.8em;
}
.category-bar {
    display: flex;
    overflow-x: auto;
    gap: 10px;
    padding: 4px 4px 16px 4px;
    margin-bottom: 20px;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
}
.category-bar::-webkit-scrollbar { display: none; }
.cat-btn {
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(255,255,255,0.06);
    color: var(--text-gray);
    padding: 8px 22px;
    border-radius: 50px;
    cursor: pointer;
    white-space: nowrap;
    font-size: 0.85em;
    font-weight: 500;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
    backdrop-filter: blur(10px);
}
.cat-btn:hover {
    background: rgba(16, 185, 129, 0.1);
    color: var(--text-white);
    border-color: rgba(16, 185, 129, 0.2);
}
.cat-btn.active {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: white;
    border-color: transparent;
    box-shadow: 0 4px 20px var(--primary-glow);
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 20px;
}
.card {
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9));
    border-radius: 18px;
    padding: 20px 16px 18px;
    text-align: center;
    border: 1px solid var(--border-color);
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
    backdrop-filter: blur(10px);
    animation: scaleIn 0.4s ease;
}
.featured-card {
    border-color: rgba(74, 163, 255, .62);
    background: linear-gradient(150deg, rgba(20, 49, 83, .96), rgba(10, 20, 36, .98));
    box-shadow: 0 0 0 1px rgba(74, 163, 255, .12), 0 12px 32px rgba(25, 106, 194, .18);
}
.featured-card:hover { border-color: #70b8ff; box-shadow: 0 18px 38px rgba(25, 106, 194, .28); }
.featured-card .sort-badge { color: #d9edff; background: rgba(31, 111, 190, .68); border-color: rgba(122, 190, 255, .45); }
.card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(180deg, rgba(16, 185, 129, 0.03), transparent);
    opacity: 0;
    transition: opacity 0.4s ease;
    border-radius: 18px;
    pointer-events: none;
}
.card:hover {
    transform: translateY(-8px) scale(1.01);
    border-color: rgba(16, 185, 129, 0.3);
    box-shadow: 0 20px 40px rgba(0,0,0,0.4), 0 0 30px rgba(16, 185, 129, 0.05);
}
.card:hover::before { opacity: 1; }
.card .sort-badge {
    position: absolute;
    top: 12px;
    left: 12px;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(10px);
    font-size: 0.6em;
    padding: 4px 10px;
    border-radius: 8px;
    color: var(--text-gray);
    font-weight: 500;
    letter-spacing: 0.3px;
    border: 1px solid rgba(255,255,255,0.05);
}
.card .card-img-container {
    height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 8px 0 12px;
    background: rgba(0,0,0,0.2);
    border-radius: 12px;
    padding: 10px;
}
.card .card-img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    filter: drop-shadow(0 4px 20px rgba(0,0,0,0.5));
    transition: transform 0.3s ease;
}
.card:hover .card-img {
    transform: scale(1.05);
}
.card .price {
    font-size: 1.1em;
    font-weight: 800;
    margin: 12px 0 8px;
    background: rgba(0,0,0,0.3);
    padding: 8px 12px;
    border-radius: 10px;
    color: var(--text-white);
    letter-spacing: 0.5px;
}
.card .expire {
    font-size: 0.7em;
    color: var(--text-gray);
    margin-bottom: 14px;
    font-family: 'Inter', sans-serif;
    letter-spacing: 0.3px;
}
.card .btn-send {
    background: linear-gradient(135deg, #3b82f6, #2563eb);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 12px;
    font-weight: 700;
    font-size: 0.85em;
    cursor: pointer;
    width: 100%;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
    position: relative;
    overflow: hidden;
}
.card .btn-send:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(59, 130, 246, 0.3);
}
.card .btn-send:active {
    transform: scale(0.96);
}
.modal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.7);
    backdrop-filter: blur(20px);
    align-items: center;
    justify-content: center;
    z-index: 9999;
    animation: fadeInUp 0.3s ease;
}
.modal.show { display: flex; }
.modal-content {
    background: linear-gradient(180deg, #1e293b, #0f172a);
    padding: 35px 30px 30px;
    border-radius: 24px;
    width: 90%;
    max-width: 420px;
    text-align: center;
    border: 1px solid rgba(16, 185, 129, 0.2);
    box-shadow: 0 30px 80px rgba(0,0,0,0.6);
    animation: scaleIn 0.3s ease;
}
.modal-content .modal-icon {
    font-size: 2.5em;
    margin-bottom: 10px;
}
.modal-content h2 {
    color: var(--text-white);
    font-size: 1.3em;
    font-weight: 700;
    margin-bottom: 6px;
}
.modal-content .modal-desc {
    color: var(--text-gray);
    font-size: 0.85em;
    margin-bottom: 20px;
}
.modal-content input, .modal-content select {
    width: 100%;
    padding: 14px 16px;
    border-radius: 12px;
    border: 2px solid rgba(255,255,255,0.06);
    background: rgba(15, 23, 42, 0.8);
    color: var(--text-white);
    font-size: 0.95em;
    outline: none;
    margin-bottom: 12px;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
}
.modal-content input:focus, .modal-content select:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px var(--primary-glow);
}
.modal-field { margin: 0 0 8px; text-align: left; }
.modal-field label { display: block; margin: 0 0 6px; color: var(--text-gray); font-size: .78rem; }
.modal-content select option { background: #0b1422; color: #edf5ff; }
.gift-total { min-height: 1.35em; margin: 0 0 14px; color: #a9d4ff; font-weight: 700; font-size: .9rem; }
.card .btn-send:disabled { cursor: not-allowed; opacity: .5; transform: none; box-shadow: none; }
.modal-content input::placeholder {
    color: rgba(148, 163, 184, 0.4);
}
.modal-btns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 6px;
}
.modal-btns button {
    padding: 13px;
    border-radius: 12px;
    border: none;
    font-weight: 700;
    font-size: 0.9em;
    cursor: pointer;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
}
.modal-btns .btn-confirm {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: white;
}
.modal-btns .btn-confirm:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 8px 30px var(--primary-glow);
}
.modal-btns .btn-confirm:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}
.modal-btns .btn-cancel {
    background: rgba(71, 85, 105, 0.5);
    color: var(--text-gray);
}
.modal-btns .btn-cancel:hover {
    background: rgba(71, 85, 105, 0.8);
    color: var(--text-white);
}
.toast-container {
    position: fixed;
    bottom: 30px;
    right: 30px;
    z-index: 10000;
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 380px;
    width: 100%;
}
.toast {
    padding: 14px 20px;
    border-radius: 14px;
    backdrop-filter: blur(20px);
    color: white;
    font-weight: 500;
    font-size: 0.9em;
    animation: slideDown 0.4s ease;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
    display: flex;
    align-items: center;
    gap: 12px;
    border: 1px solid rgba(255,255,255,0.05);
}
.toast.success { background: rgba(16, 185, 129, 0.9); }
.toast.error { background: rgba(239, 68, 68, 0.9); }
.toast.info { background: rgba(59, 130, 246, 0.9); }
.toast .toast-icon { font-size: 1.3em; }
@media (max-width: 1024px) {
    .grid { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
}
@media (max-width: 768px) {
    .wallet-bar { grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px 16px; }
    .wallet-item.full { grid-column: span 2; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px; }
    .main-header h1 { font-size: 1.6em; }
    .login-container { margin: 30px 16px; padding: 30px 24px; }
    .store-container { padding: 0 14px; }
    .store-header h3 { font-size: 1.1em; }
    .card .card-img-container { height: 90px; }
    .card { padding: 14px 12px 14px; }
    .modal-content { padding: 25px 20px; }
    .toast-container { bottom: 16px; right: 16px; left: 16px; max-width: none; }
}
@media (max-width: 480px) {
    .grid { grid-template-columns: 1fr 1fr; gap: 10px; }
    .card .price { font-size: 0.9em; }
    .card .btn-send { font-size: 0.75em; padding: 8px 12px; }
    .modal-btns { grid-template-columns: 1fr; }
    .wallet-bar { grid-template-columns: 1fr 1fr; }
}

/* Marcos Dev visual identity */
:root {
    --primary: #57a6ff;
    --primary-dark: #2878d0;
    --primary-glow: rgba(57, 145, 255, .24);
    --bg-dark: #070d17;
    --bg-card: rgba(15, 29, 26, .82);
    --border-color: rgba(57, 145, 255, .17);
    --text-white: #edf5ff;
    --text-gray: #9babc0;
    --shadow: 0 28px 80px rgba(0, 0, 0, .48);
}
body {
    background-image: radial-gradient(ellipse at 12% 6%, rgba(22, 78, 145, .24), transparent 38%),
        radial-gradient(ellipse at 92% 45%, rgba(36, 106, 190, .18), transparent 36%),
        linear-gradient(145deg, #070d17 0%, #0a1422 52%, #101827 100%);
}
.main-header {
    padding: 24px 24px 21px;
    background: rgba(7, 13, 23, .82);
    border-bottom-color: rgba(57, 145, 255, .2);
}
.main-header h1 {
    margin: 0;
    color: #e7f3ff;
    font-size: clamp(1.9rem, 5vw, 2.65rem);
    font-weight: 800;
    letter-spacing: -.04em;
    text-shadow: 0 5px 24px rgba(57, 145, 255, .17);
}
.main-header .subtitle {
    margin-top: 8px;
    font-size: .76rem;
    letter-spacing: .19em;
    text-transform: uppercase;
}
.main-header .subtitle span { color: #57a6ff; -webkit-text-fill-color: #57a6ff; }
.login-container {
    position: relative;
    overflow: hidden;
    margin-top: 54px;
    border: 1px solid rgba(57, 145, 255, .24);
    background: linear-gradient(145deg, rgba(15, 29, 48, .95), rgba(8, 16, 29, .93));
    box-shadow: 0 30px 90px rgba(0, 0, 0, .42), inset 0 1px rgba(255,255,255,.04);
}
.login-container::before {
    content: '';
    position: absolute;
    width: 220px; height: 220px; right: -105px; top: -120px;
    border: 1px solid rgba(57,145,255,.2); border-radius: 50%;
    box-shadow: 0 0 0 22px rgba(57,145,255,.035), 0 0 0 48px rgba(57,145,255,.025);
    pointer-events: none;
}
.login-container .logo-icon {
    width: 66px; height: 66px; display: grid; place-items: center;
    margin-bottom: 22px; border-radius: 21px;
    background: linear-gradient(145deg, rgba(57,145,255,.2), rgba(24,91,166,.24));
    border: 1px solid rgba(57,145,255,.32);
    box-shadow: 0 12px 32px rgba(0,0,0,.2);
}
.login-container h2 { letter-spacing: -.035em; font-size: 1.7rem; }
.login-container .login-desc { line-height: 1.65; }
.login-container .input-group input {
    border-color: rgba(57,145,255,.16);
    background: rgba(4, 12, 10, .72);
}
.login-container .input-group input:focus { border-color: var(--primary); }
.login-container .btn-primary, .btn-confirm {
    color: #07101d;
    background: linear-gradient(115deg, #a9d4ff, #398de5 55%, #77baff);
    box-shadow: 0 10px 28px rgba(57,145,255,.22);
}
.login-container .btn-primary:hover, .btn-confirm:hover {
    box-shadow: 0 14px 34px rgba(57,145,255,.32);
    filter: brightness(1.06);
}
.store-container { max-width: 1280px; }
.wallet-bar, .card, .modal-content {
    border-color: rgba(57,145,255,.18);
    background: linear-gradient(145deg, rgba(15,29,48,.92), rgba(8,16,29,.93));
}
.store-header h3 span { color: #8dc5ff; }
.cat-btn.active, .cat-btn:hover, .card .btn-send {
    color: #07101d;
    background: linear-gradient(115deg, #a9d4ff, #398de5);
}
.card:hover { border-color: rgba(57,145,255,.5); }
.main-footer {
    padding: 28px 16px 34px; color: #8392a8; text-align: center;
    font-size: .72rem; letter-spacing: .17em; text-transform: uppercase;
}
.main-footer strong { color: #57a6ff; font-weight: 700; }
@media (max-width: 600px) {
    .main-header { padding: 19px 14px 17px; }
    .login-container { margin: 34px 16px; padding: 34px 25px; }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; }
}
.account-banner { display:flex; align-items:center; gap:16px; margin:0 0 22px; padding:17px 20px; border:1px solid rgba(57,145,255,.28); border-radius:18px; background:linear-gradient(110deg, rgba(25,76,135,.35), rgba(12,23,40,.9) 66%); box-shadow:inset 0 1px rgba(255,255,255,.04), 0 12px 35px rgba(0,0,0,.18); }
.account-avatar { display:grid; place-items:center; flex:0 0 46px; width:46px; height:46px; border-radius:15px; color:#e7f3ff; font-weight:800; font-size:1.05rem; background:linear-gradient(145deg,#318ce8,#174b85); box-shadow:0 8px 22px rgba(29,112,201,.28); }
.account-copy { min-width:0; } .account-label { color:#8ca4c2; font-size:.68rem; letter-spacing:.16em; text-transform:uppercase; }
.account-name { color:#f2f7ff; margin-top:4px; font-size:1.05rem; font-weight:700; overflow-wrap:anywhere; } .account-id { color:#96abc6; margin-top:3px; font-size:.76rem; }
@media(max-width:600px) { .account-banner { padding:14px; } }</style>
</head>
<body>
<header class="main-header">
    <h1>Marcos Dev</h1>
    <div class="subtitle"><span>Free Fire</span> · Estudio de regalos</div>
</header>
<div class="login-container" id="loginBox">
    <span class="logo-icon">🎁</span>
    <h2>Bienvenido</h2>
    <p class="login-desc">Conecta tu cuenta para explorar el catálogo y enviar regalos</p>
    <div class="input-group">
        <input type="text" id="accessInput" placeholder="Pega aquí tu token de acceso..." autocomplete="off">
    </div>
    <button class="btn-primary" id="generateBtn">
        <span id="btnText">🚀 Generar JWT y cargar tienda</span>
    </button>
    <div class="divider">o</div>
    <div class="input-group">
        <input type="text" id="jwtInput" placeholder="O pega aquí un JWT existente..." autocomplete="off">
    </div>
    <button class="btn-primary" id="loadBtn" style="background: linear-gradient(115deg, #a9d4ff, #398de5);">
        🔑 Usar JWT existente
    </button>
    <div class="error-msg" id="errorMsg">⚠️ Mensaje de error</div>
    <div class="success-msg" id="successMsg">✅ ¡JWT generado correctamente!</div>
</div>
<div class="store-container" id="storeBox" style="display: none;">
    <div class="account-banner"><div class="account-avatar" id="accountAvatar">M</div><div class="account-copy"><div class="account-label">Cuenta conectada</div><div class="account-name" id="accountName">Buscando cuenta...</div><div class="account-id" id="accountId"></div></div></div>
    <div class="wallet-bar" id="walletBar">
        <div class="wallet-item"><span class="label">💎 Diamantes</span><span class="value diamond" id="valDiamond">--</span></div>
        <div class="wallet-item"><span class="label">🪙 Oro</span><span class="value gold" id="valGold">--</span></div>
        <div class="wallet-item full"><span class="label">⏱️ Última recarga</span><span class="value topup" id="valTopup">--</span></div>
    </div>
    <div class="store-header">
        <h3>🛒 <span>Catálogo</span> de la tienda</h3>
        <div class="sent-badge">🎁 Enviados hoy <span class="count" id="giftsSent">0</span></div>
    </div>
    <div class="category-bar" id="categoryBar">
        <button class="cat-btn active" data-cat="All">✨ Todos los artículos</button>
    </div>
    <div class="grid" id="itemsGrid"></div>
</div>
<div class="modal" id="giftModal">
    <div class="modal-content">
        <div class="modal-icon">🎁</div>
        <h2>Enviar regalo</h2>
        <p class="modal-desc">Ingresa el UID del destinatario y los detalles del regalo</p>
        <input type="text" id="targetUid" placeholder="UID del destinatario" inputmode="numeric" autocomplete="off">
        <div class="modal-field" id="giftCurrencyField">
            <label for="giftCurrency">Moneda</label>
            <select id="giftCurrency"></select>
        </div>
        <div class="modal-field">
            <label for="giftQuantity">Cantidad (máximo 999)</label>
            <input type="number" id="giftQuantity" min="1" max="999" step="1" value="1" inputmode="numeric">
        </div>
        <p class="gift-total" id="giftTotal" aria-live="polite"></p>
        <input type="text" id="giftMsg" placeholder="Mensaje (opcional)" value="¡Disfruta tu regalo! 🎉">
        <div class="modal-btns">
            <button class="btn-confirm" id="confirmSend">✅ CONFIRMAR</button>
            <button class="btn-cancel" onclick="closeModal()">✖ CANCELAR</button>
        </div>
    </div>
</div>
<div class="toast-container" id="toastContainer"></div>
<footer class="main-footer">Diseñado por <strong>Marcos Dev</strong></footer>
<script>
let currentJWT = "", currentPage = 1, isLoading = false, hasMoreItems = true, currentCategory = "All";
let selectedGift = {};
const $ = id => document.getElementById(id);
const accessInput = $('accessInput'), jwtInput = $('jwtInput');
const generateBtn = $('generateBtn'), loadBtn = $('loadBtn');
const errorMsg = $('errorMsg'), successMsg = $('successMsg');
const loginBox = $('loginBox'), storeBox = $('storeBox');
const itemsGrid = $('itemsGrid'), categoryBar = $('categoryBar');
const valDiamond = $('valDiamond'), valGold = $('valGold'), valTopup = $('valTopup');
const giftsSent = $('giftsSent'), giftModal = $('giftModal');
const accountNameEl = $('accountName'), accountIdEl = $('accountId'), accountAvatar = $('accountAvatar');
const targetUid = $('targetUid'), giftMsg = $('giftMsg'), confirmSend = $('confirmSend');
const giftQuantity = $('giftQuantity'), giftCurrency = $('giftCurrency'), giftCurrencyField = $('giftCurrencyField'), giftTotal = $('giftTotal');
const toastContainer = $('toastContainer');
function showToast(message, type = 'info') {
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = icons[type] || 'ℹ️';
    const text = document.createElement('span');
    text.textContent = String(message);
    toast.append(icon, text);
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100px)';
        toast.style.transition = 'all 0.4s ease';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}
function setLoading(btn, loading) {
    if (loading) {
        btn.disabled = true;
        btn.innerHTML = '<span class="loader"></span> Procesando...';
    } else {
        btn.disabled = false;
        btn.innerHTML = btn === generateBtn ? '🚀 Generar JWT y cargar tienda' : '🔑 Usar JWT existente';
    }
}
function showError(msg) {
    errorMsg.textContent = '⚠️ ' + msg;
    errorMsg.classList.add('show');
    successMsg.classList.remove('show');
}
function showSuccess(msg) {
    successMsg.textContent = '✅ ' + msg;
    successMsg.classList.add('show');
    errorMsg.classList.remove('show');
}
function hideMessages() {
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
}
async function generateJWT(accessToken) {
    try {
        const res = await fetch('/api/generate_jwt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ access_token: accessToken })
        });
        const data = await res.json();
        if (data.success) return data.jwt;
        else { showError(data.message || 'No se pudo generar el JWT'); return null; }
    } catch (e) { showError('Error de conexión: ' + e.message); return null; }
}
async function fetchAndRenderItems(refreshCats = false) {
    if (isLoading || !hasMoreItems) return;
    isLoading = true;
    try {
        const response = await fetch('/api/get_store', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jwt: currentJWT, page: currentPage, limit: 24, category: currentCategory })
        });
        const data = await response.json();
        if (data.success) {
            if (data.wallet) {
                valDiamond.textContent = '💎 ' + data.wallet.diamond;
                valGold.textContent = '🪙 ' + data.wallet.gold;
                valTopup.textContent = data.wallet.last_topup;
            }
            giftsSent.textContent = data.sent_today;
            const shownName = data.account_name || (data.account_id ? 'Jugador de Free Fire' : 'Cuenta identificada');
            accountNameEl.textContent = shownName;
            accountIdEl.textContent = data.account_id ? 'UID ' + data.account_id : 'Nombre no incluido en el JWT';
            accountAvatar.textContent = shownName.trim().charAt(0).toUpperCase() || 'M';
            if (refreshCats) renderCategories(data.categories);
            data.items.forEach((item, index) => {
                const card = document.createElement('div');
                card.className = item.featured_name ? 'card featured-card' : 'card';
                card.style.animationDelay = (index * 0.04) + 's';

                const badge = document.createElement('div');
                badge.className = 'sort-badge';
                badge.textContent = item.featured_name || item.category || 'Otros';

                const imageContainer = document.createElement('div');
                imageContainer.className = 'card-img-container';
                const image = document.createElement('img');
                image.src = '/api/image/' + encodeURIComponent(item.item_id);
                image.className = 'card-img';
                image.alt = 'Artículo ' + String(item.item_id || '');
                image.loading = 'lazy';
                imageContainer.appendChild(image);

                const price = document.createElement('div');
                price.className = 'price';
                price.textContent = item.price_str || 'Precio no disponible';

                const expiration = document.createElement('div');
                expiration.className = 'expire';
                expiration.textContent = '⏳ ' + (item.expire_date || 'Sin fecha');

                const sendButton = document.createElement('button');
                sendButton.className = 'btn-send';
                sendButton.textContent = '🚀 Enviar';
                const hasPrice = Number(item.gems_price) > 0 || Number(item.coins_price) > 0;
                const hasCommodity = Number(item.commodity_id) > 0;
                sendButton.disabled = !hasCommodity || !hasPrice;
                if (!hasCommodity || !hasPrice) sendButton.title = 'Artículo no disponible para regalar';
                else sendButton.addEventListener('click', () => openModal(item));

                card.append(badge, imageContainer, price, expiration, sendButton);
                itemsGrid.appendChild(card);
            });
            hasMoreItems = data.has_more;
            currentPage++;
        } else {
            showToast(data.message || 'No se pudo cargar la tienda', 'error');
        }
    } catch (err) { showToast('Error de conexión: ' + err.message, 'error'); }
    isLoading = false;
}
function renderCategories(categories) {
    categoryBar.replaceChildren();
    const addCategory = (label, value, active = false) => {
        const btn = document.createElement('button');
        btn.className = 'cat-btn' + (active ? ' active' : '');
        btn.textContent = label;
        btn.onclick = () => {
            document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentCategory = value;
            currentPage = 1;
            hasMoreItems = true;
            itemsGrid.innerHTML = '';
            fetchAndRenderItems();
        };
        categoryBar.appendChild(btn);
    };
    addCategory('✨ Todos los artículos', 'All', true);
    addCategory('⭐ Destacados', 'Featured');
    categories.forEach(cat => addCategory(cat, cat));
}
function openModal(item) {
    selectedGift = {
        commodityId: String(item.commodity_id),
        gemsPrice: Number(item.gems_price) || 0,
        coinsPrice: Number(item.coins_price) || 0
    };
    giftCurrency.replaceChildren();
    if (selectedGift.gemsPrice > 0) {
        giftCurrency.add(new Option('💎 Diamantes · ' + selectedGift.gemsPrice + ' c/u', 'diamond'));
    }
    if (selectedGift.coinsPrice > 0) {
        giftCurrency.add(new Option('🪙 Oro · ' + selectedGift.coinsPrice + ' c/u', 'gold'));
    }
    giftCurrencyField.hidden = giftCurrency.options.length < 2;
    giftQuantity.value = '1';
    updateGiftTotal();
    giftModal.classList.add('show');
    targetUid.value = '';
    targetUid.focus();
}
function updateGiftTotal() {
    const quantity = Number(giftQuantity.value);
    const currency = giftCurrency.value || (selectedGift.gemsPrice > 0 ? 'diamond' : 'gold');
    const unitPrice = currency === 'diamond' ? selectedGift.gemsPrice : selectedGift.coinsPrice;
    const symbol = currency === 'diamond' ? '💎' : '🪙';
    giftTotal.textContent = Number.isInteger(quantity) && quantity > 0 && unitPrice > 0
        ? `Total estimado: ${symbol} ${(quantity * unitPrice).toLocaleString('es-AR')}`
        : 'Ingresa una cantidad válida';
}
function closeModal() { giftModal.classList.remove('show'); }
confirmSend.addEventListener('click', async () => {
    const uid = targetUid.value.trim();
    const msg = giftMsg.value.trim() || '¡Disfruta tu regalo! 🎉';
    const quantity = Number(giftQuantity.value);
    if (!/^\d+$/.test(uid) || Number(uid) <= 0) { showToast('Ingresa un UID numérico válido', 'error'); return; }
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 999) { showToast('La cantidad debe estar entre 1 y 999', 'error'); return; }
    confirmSend.disabled = true;
    confirmSend.textContent = '⏳ Enviando...';
    try {
        const res = await fetch('/api/send_gift', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jwt: currentJWT, receiver_uid: uid, commodity_id: selectedGift.commodityId,
                quantity, currency: giftCurrency.value, message: msg
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`🎁 ¡${quantity} artículo(s) enviado(s) a ${uid}!`, 'success');
            closeModal();
            currentPage = 1; hasMoreItems = true; itemsGrid.innerHTML = '';
            fetchAndRenderItems();
        } else { showToast(data.message || 'No se pudo enviar el regalo', 'error'); }
    } catch (e) { showToast('Error: ' + e.message, 'error'); }
    confirmSend.disabled = false;
    confirmSend.textContent = '✅ CONFIRMAR';
});
generateBtn.addEventListener('click', async () => {
    const access = accessInput.value.trim();
    if (!access) { showError('Ingresa un token de acceso'); return; }
    hideMessages();
    setLoading(generateBtn, true);
    const jwt = await generateJWT(access);
    if (jwt) {
        currentJWT = jwt;
        showSuccess('¡JWT generado correctamente! Cargando la tienda...');
        accessInput.classList.add('success');
        loginBox.style.display = 'none';
        storeBox.style.display = 'block';
        currentPage = 1; hasMoreItems = true; currentCategory = 'All';
        itemsGrid.innerHTML = '';
        await fetchAndRenderItems(true);
        showToast('✅ ¡Tienda cargada correctamente!', 'success');
    }
    setLoading(generateBtn, false);
});
loadBtn.addEventListener('click', async () => {
    const jwt = jwtInput.value.trim();
    if (!jwt) { showError('Pega tu token JWT'); return; }
    hideMessages();
    setLoading(loadBtn, true);
    try {
        const parts = jwt.split('.');
        if (parts.length !== 3) { showError('Formato de JWT inválido'); setLoading(loadBtn, false); return; }
        currentJWT = jwt;
        showSuccess('¡JWT cargado! Cargando la tienda...');
        loginBox.style.display = 'none';
        storeBox.style.display = 'block';
        currentPage = 1; hasMoreItems = true; currentCategory = 'All';
        itemsGrid.innerHTML = '';
        await fetchAndRenderItems(true);
        showToast('✅ ¡Tienda cargada correctamente!', 'success');
    } catch (e) { showError('JWT inválido: ' + e.message); }
    setLoading(loadBtn, false);
});
window.addEventListener('scroll', () => {
    if (storeBox.style.display !== 'none') {
        const scrollHeight = document.documentElement.scrollHeight;
        const scrollTop = window.scrollY;
        const clientHeight = window.innerHeight;
        if (scrollTop + clientHeight >= scrollHeight - 400) fetchAndRenderItems();
    }
});
accessInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') generateBtn.click(); });
jwtInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') loadBtn.click(); });
targetUid.addEventListener('keydown', (e) => { if (e.key === 'Enter') confirmSend.click(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
giftQuantity.addEventListener('input', updateGiftTotal);
giftCurrency.addEventListener('change', updateGiftTotal);
giftModal.addEventListener('click', (e) => { if (e.target === giftModal) closeModal(); });
console.log('👑 Marcos Dev: aplicación cargada correctamente');
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=False)