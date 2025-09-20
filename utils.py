import re
import math
from datetime import datetime, date
from typing import Optional
from dateutil.parser import parse
from urllib.parse import urlparse


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Limita um valor entre min e max"""
    return max(min_val, min(value, max_val))


def safe_tanh(x: float) -> float:
    """tanh seguro para evitar overflow"""
    try:
        return math.tanh(x)
    except:
        return 1.0 if x > 0 else -1.0


def compute_score(advertiser_active_ads_est: int, days_active: int, variations_count: int) -> float:
    """
    Calcula o score baseado na fórmula:
    A = clamp(advertiser_active_ads_est, 0, 50)
    D = clamp(days_active, 0, 60)
    V = max(1, variations_count)
    score = 100 * (0.5*(A/50) + 0.3*(D/60) + 0.2*tanh(V/5))
    """
    A = clamp(float(advertiser_active_ads_est or 0), 0.0, 50.0)
    D = clamp(float(days_active or 0), 0.0, 60.0)
    V = max(1.0, float(variations_count or 1))
    
    score = 100 * (0.5 * (A / 50.0) + 0.3 * (D / 60.0) + 0.2 * safe_tanh(V / 5.0))
    return round(score, 2)


def parse_date_any(date_text: str) -> Optional[str]:
    """
    Parse data em português ou inglês e retorna formato YYYY-MM-DD
    """
    if not date_text:
        return None
    
    try:
        # Limpar texto e extrair data
        date_text = date_text.strip()
        
        # Padrões comuns
        patterns = [
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # dd/mm/yyyy
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # yyyy-mm-dd
            r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})',  # dd de mês de yyyy
            r'(\w+)\s+(\d{1,2}),?\s+(\d{4})',  # Month dd, yyyy
            r'(\d{1,2})\s+(\w+)\s+(\d{4})',  # dd Month yyyy
        ]
        
        # Mapeamento de meses em português
        meses_pt = {
            'janeiro': '01', 'jan': '01',
            'fevereiro': '02', 'fev': '02',
            'março': '03', 'mar': '03',
            'abril': '04', 'abr': '04',
            'maio': '05', 'mai': '05',
            'junho': '06', 'jun': '06',
            'julho': '07', 'jul': '07',
            'agosto': '08', 'ago': '08',
            'setembro': '09', 'set': '09',
            'outubro': '10', 'out': '10',
            'novembro': '11', 'nov': '11',
            'dezembro': '12', 'dez': '12'
        }
        
        # Primeiro tenta usar dateutil para casos simples
        try:
            parsed = parse(date_text, fuzzy=True, dayfirst=True)
            return parsed.strftime('%Y-%m-%d')
        except:
            pass
        
        # Fallback: regex patterns
        for pattern in patterns:
            match = re.search(pattern, date_text.lower())
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    if pattern == patterns[2]:  # dd de mês de yyyy
                        day, month_name, year = groups
                        month = meses_pt.get(month_name.lower(), '01')
                        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    elif pattern == patterns[3]:  # Month dd, yyyy
                        month_name, day, year = groups
                        month = meses_pt.get(month_name.lower(), '01')
                        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    elif pattern == patterns[4]:  # dd Month yyyy
                        day, month_name, year = groups
                        month = meses_pt.get(month_name.lower(), '01')
                        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    else:  # Formatos numéricos
                        if pattern == patterns[0]:  # dd/mm/yyyy
                            day, month, year = groups
                            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        elif pattern == patterns[1]:  # yyyy-mm-dd
                            year, month, day = groups
                            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        return None
        
    except Exception as e:
        print(f"Erro ao fazer parse da data '{date_text}': {e}")
        return None


def days_between(date_str: str, today: Optional[date] = None) -> int:
    """Calcula dias entre uma data e hoje"""
    if not date_str:
        return 0
    
    if today is None:
        today = date.today()
    
    try:
        start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        delta = today - start_date
        return max(0, delta.days)
    except:
        return 0


def is_marketplace(url: str) -> bool:
    """Verifica se a URL é de um marketplace conhecido"""
    if not url:
        return False
    
    url_lower = url.lower()
    marketplaces = [
        'mercadolivre.com', 'mercadolibre.com',
        'amazon.com', 'amazon.com.br',
        'shopee.com.br',
        'magazineluiza.com.br', 'magalu.com.br',
        'americanas.com.br',
        'casasbahia.com.br',
        'submarino.com.br',
        'extra.com.br',
        'pontofrio.com.br'
    ]
    
    return any(marketplace in url_lower for marketplace in marketplaces)


def is_probable_dropshipping(url: str) -> bool:
    """
    Detecta se uma URL provavelmente é de dropshipping
    baseado em padrões conhecidos
    """
    if not url:
        return False
    
    url_lower = url.lower()
    
    # Padrões que indicam dropshipping
    dropshipping_patterns = [
        'myshopify.com',
        '/products/',
        'yampi.com.br',
        'appmax.com.br',
        'cartpanda.com.br',
        'nuvemshop.com.br',
        'tray.com.br',
        'loja.com.br',
        'checkout',
        'comprar-agora',
        'add-to-cart',
        'produto-'
    ]
    
    return any(pattern in url_lower for pattern in dropshipping_patterns)


def extract_domain(url: str) -> str:
    """Extrai domínio de uma URL"""
    if not url:
        return ""
    
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except:
        return ""


def normalize_text(text: str) -> str:
    """Normaliza texto removendo caracteres especiais e espaços extras"""
    if not text:
        return ""
    
    # Remove quebras de linha e espaços extras
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Remove caracteres não imprimíveis
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    return text


def extract_ad_id_from_url(url: str) -> Optional[str]:
    """Extrai ID do anúncio de uma URL da Ads Library"""
    if not url:
        return None
    
    try:
        # Padrões comuns de ID na URL
        patterns = [
            r'ad_id=([^&]+)',
            r'/ads/(\d+)',
            r'creative_id=([^&]+)',
            r'id=([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    except:
        return None


def estimate_variations_from_text(text: str) -> int:
    """Estima número de variações baseado no texto"""
    if not text:
        return 1
    
    # Procura por indicadores de múltiplas variações
    variation_indicators = [
        r'(\d+)\s*(versões|variações|opções)',
        r'disponível\s+em\s+(\d+)',
        r'(\d+)\s*cores',
        r'(\d+)\s*tamanhos'
    ]
    
    for pattern in variation_indicators:
        match = re.search(pattern, text.lower())
        if match:
            try:
                count = int(match.group(1))
                return min(count, 20)  # Limita a 20 para evitar valores absurdos
            except:
                continue
    
    return 1


def clean_headline(headline: str) -> str:
    """Limpa e normaliza headline do anúncio"""
    if not headline:
        return ""
    
    # Remove prefixos comuns desnecessários
    prefixes_to_remove = [
        "Anúncio",
        "Ad:",
        "Sponsored:",
        "Patrocinado:"
    ]
    
    for prefix in prefixes_to_remove:
        if headline.startswith(prefix):
            headline = headline[len(prefix):].strip()
    
    return normalize_text(headline)