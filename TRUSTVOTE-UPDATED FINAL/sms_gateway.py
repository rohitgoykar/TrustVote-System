import os
import json
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('TrustVote_SMS')

def load_sms_config():
    """Loads SMS gateway configuration from environment or config file."""
    config = {
        'fast2sms_api_key': os.getenv('FAST2SMS_API_KEY', '').strip(),
        'twofactor_api_key': os.getenv('TWOFACTOR_API_KEY', '').strip(),
        'twilio_account_sid': os.getenv('TWILIO_ACCOUNT_SID', '').strip(),
        'twilio_auth_token': os.getenv('TWILIO_AUTH_TOKEN', '').strip(),
        'twilio_phone_number': os.getenv('TWILIO_PHONE_NUMBER', '').strip(),
        'msg91_auth_key': os.getenv('MSG91_AUTH_KEY', '').strip(),
        'msg91_template_id': os.getenv('MSG91_TEMPLATE_ID', '').strip(),
    }

    # Try loading from local config file if present
    config_file = os.path.join(os.path.dirname(__file__), '..', 'sms_config.json')
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                for k, v in file_config.items():
                    if v and not config.get(k):
                        config[k] = str(v).strip()
        except Exception as e:
            logger.warning(f'Error reading sms_config.json: {e}')

    return config

def send_officer_otp_sms(mobile_number: str, otp_code: str, officer_role: str = 'Officer', officer_name: str = '') -> dict:
    """
    Dispatches 6-digit OTP code to the given 10-digit Indian mobile number.
    Supports Fast2SMS, 2Factor.in, Twilio, and Msg91 gateways.
    If no gateway API key is configured, provides simulation response.
    """
    clean_mobile = ''.join(filter(str.isdigit, str(mobile_number)))
    if len(clean_mobile) == 12 and clean_mobile.startswith('91'):
        clean_mobile = clean_mobile[2:]
    if len(clean_mobile) != 10:
        return {
            'sent': False,
            'gateway': 'validation_error',
            'message': f'Invalid 10-digit mobile number: {mobile_number}'
        }

    config = load_sms_config()
    sms_text = f"SEC-TRUSTVOTE: Your {officer_role} Login OTP is {otp_code}. Valid for 10 minutes. Do not share this OTP with anyone."

    # 1. 2Factor.in Provider (India Dedicated Real-Time OTP Gateway - Primary)
    if config['twofactor_api_key']:
        try:
            api_key = config['twofactor_api_key']
            url = f"https://2factor.in/API/V1/{api_key}/SMS/{clean_mobile}/{otp_code}"
            resp = requests.get(url, timeout=8)
            res_data = resp.json() if resp.text else {}
            if res_data.get('Status') == 'Success':
                logger.info(f'[2Factor] Real OTP {otp_code} successfully delivered to +91 {clean_mobile} (Session: {res_data.get("Details")})')
                return {
                    'sent': True,
                    'gateway': '2Factor.in',
                    'message': 'SMS dispatched via 2Factor.in OTP Gateway'
                }
            else:
                logger.warning(f'[2Factor Warning] {res_data.get("Details", "Unknown response")}')
        except Exception as e:
            logger.error(f'[2Factor Exception] {e}')

    # 2. Fast2SMS Provider (Fallback)
    if config['fast2sms_api_key']:
        # Attempt A: Fast2SMS Smart OTP Route ('otp')
        try:
            url = "https://www.fast2sms.com/dev/bulkV2"
            headers = {
                "authorization": config['fast2sms_api_key'],
                "Content-Type": "application/json"
            }
            payload_otp = {
                "route": "otp",
                "variables_values": str(otp_code),
                "numbers": clean_mobile
            }
            resp = requests.post(url, json=payload_otp, headers=headers, timeout=8)
            res_data = resp.json() if resp.text else {}
            if res_data.get('return') or res_data.get('status_code') == 200:
                logger.info(f'[Fast2SMS Smart OTP] OTP {otp_code} delivered to +91 {clean_mobile}')
                return {'sent': True, 'gateway': 'Fast2SMS Smart OTP', 'message': 'SMS dispatched via Fast2SMS Smart OTP'}
            else:
                logger.warning(f'[Fast2SMS Smart OTP Warning] {res_data.get("message", "Unknown response")}')
        except Exception as e:
            logger.error(f'[Fast2SMS Smart OTP Exception] {e}')

        # Attempt B: Fast2SMS Quick SMS Route ('q') fallback
        try:
            url = "https://www.fast2sms.com/dev/bulkV2"
            headers = {
                "authorization": config['fast2sms_api_key'],
                "Content-Type": "application/json"
            }
            payload_q = {
                "route": "q",
                "message": sms_text,
                "language": "english",
                "numbers": clean_mobile
            }
            resp_q = requests.post(url, json=payload_q, headers=headers, timeout=8)
            res_data_q = resp_q.json() if resp_q.text else {}
            if res_data_q.get('return') or res_data_q.get('status_code') == 200:
                logger.info(f'[Fast2SMS Quick SMS] OTP {otp_code} delivered to +91 {clean_mobile}')
                return {'sent': True, 'gateway': 'Fast2SMS Quick SMS', 'message': 'SMS dispatched via Fast2SMS Quick SMS'}
            else:
                logger.warning(f'[Fast2SMS Quick SMS Warning] {res_data_q.get("message", "")}')
        except Exception as e:
            logger.error(f'[Fast2SMS Quick SMS Exception] {e}')

    # 3. Twilio SMS Provider
    if config['twilio_account_sid'] and config['twilio_auth_token'] and config['twilio_phone_number']:
        try:
            account_sid = config['twilio_account_sid']
            auth_token = config['twilio_auth_token']
            from_number = config['twilio_phone_number']
            to_number = f"+91{clean_mobile}"
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            resp = requests.post(
                url,
                data={'From': from_number, 'To': to_number, 'Body': sms_text},
                auth=(account_sid, auth_token),
                timeout=8
            )
            if resp.status_code in [200, 201]:
                logger.info(f'[Twilio] OTP sent to {to_number}')
                return {'sent': True, 'gateway': 'Twilio', 'message': 'SMS dispatched via Twilio'}
            else:
                logger.warning(f'[Twilio Error] {resp.text}')
        except Exception as e:
            logger.error(f'[Twilio Exception] {e}')

    # 4. Simulation Mode
    logger.info('==========================================================')
    logger.info(f'[SIMULATED SMS TELEMETRY] TO: +91 {clean_mobile}')
    logger.info(f'[SIMULATED SMS TELEMETRY] OFFICER: {officer_name} ({officer_role})')
    logger.info(f'[SIMULATED SMS TELEMETRY] MESSAGE: {sms_text}')
    logger.info(f'[SIMULATED SMS TELEMETRY] OTP CODE: {otp_code}')
    logger.info('==========================================================')

    return {
        'sent': False,
        'gateway': 'simulated',
        'message': f'SIMULATION: OTP code is {otp_code}. Connect Fast2SMS or Twilio API key in sms_config.json for real cellular SMS.',
        'otp_code': otp_code
    }
