import requests
import time
import random
from typing import List, Optional
from bs4 import BeautifulSoup
from utils import (
    parse_date_any, days_between, is_marketplace, is_probable_dropshipping,
    normalize_text, estimate_variations_from_text, clean_headline, compute_score
)
from models import AdData, AdOut
import logging

logger = logging.getLogger(__name__)


class FacebookAdsRequestsScraper:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        
        # Headers para parecer um navegador real
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    def random_delay(self, min_delay: float = 1, max_delay: float = 3):
        """Delay aleatório para evitar detecção"""
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def search_facebook_ads(self, query: str, depth: str = "standard") -> List[AdData]:
        """
        Faz uma busca básica na Facebook Ads Library usando requests
        NOTA: Esta é uma implementação simplificada que retorna dados mock
        Para produção real, seria necessário lidar com autenticação do Facebook
        """
        ads_data = []
        
        try:
            logger.info(f"Buscando por: '{query}' com depth: {depth}")
            
            # Simula delay de rede
            self.random_delay(2, 4)
            
            # Para demonstração, vamos criar alguns dados de exemplo
            # Em produção real, seria necessário fazer scraping real ou usar Graph API
            mock_advertisers = [
                {"name": "Solar Tech BR", "domain": "solartech.myshopify.com"},
                {"name": "Lumina Store", "domain": "luminastore.com.br"},
                {"name": "Casa Solar", "domain": "casasolar.tray.com.br"},
                {"name": "Eco Light Brasil", "domain": "ecolight.yampi.com.br"},
                {"name": "Smart Solar BR", "domain": "smartsolar.nuvemshop.com.br"}
            ]
            
            count = {"fast": 3, "standard": 5, "deep": 8}.get(depth, 5)
            
            for i in range(count):
                if i < len(mock_advertisers):
                    advertiser = mock_advertisers[i]
                    
                    ad_data = AdData()
                    ad_data.advertiser_name = advertiser["name"]
                    ad_data.landing_url = f"https://{advertiser['domain']}"
                    ad_data.headline = f"⚡ {query.title()} com Sensor de Movimento - Frete Grátis!"
                    ad_data.text = f"Descubra nossa incrível {query}! Tecnologia avançada, economia garantida. Aproveite nossa promoção especial!"
                    ad_data.media_type = random.choice(["image", "video"])
                    ad_data.start_date = f"2025-{random.randint(7, 9):02d}-{random.randint(1, 28):02d}"
                    ad_data.days_active = days_between(ad_data.start_date)
                    ad_data.variations_count = random.randint(1, 5)
                    ad_data.advertiser_active_ads_est = random.randint(5, 50)
                    ad_data.is_probable_dropshipping = is_probable_dropshipping(ad_data.landing_url)
                    ad_data.ad_library_result_url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&q={query}"
                    
                    ads_data.append(ad_data)
                    
                    self.random_delay(0.5, 1.5)
            
            logger.info(f"Gerados {len(ads_data)} anúncios de demonstração")
            
        except Exception as e:
            logger.error(f"Erro na busca: {e}")
        
        return ads_data


async def buscar_criativos_facebook(descricao_produto: str, depth: str = "standard") -> List[AdOut]:
    """
    Função principal compatível - versão simplificada para demonstração
    """
    results = []
    
    try:
        scraper = FacebookAdsRequestsScraper()
        ads_data = scraper.search_facebook_ads(descricao_produto, depth)
        
        for ad_data in ads_data:
            # Calcula score
            ad_data.score = compute_score(
                ad_data.advertiser_active_ads_est,
                ad_data.days_active,
                ad_data.variations_count
            )
            
            # Cria estrutura de saída
            ad_out = AdOut(
                query=descricao_produto,
                country="BR",
                ad=ad_data
            )
            
            results.append(ad_out)
        
        # Ordena por score (desc) e days_active (desc)
        results.sort(key=lambda x: (-x.ad.score, -x.ad.days_active))
        
        return results
        
    except Exception as e:
        logger.error(f"Erro na função buscar_criativos_facebook: {e}")
        return []


if __name__ == "__main__":
    # Teste simples
    import asyncio
    
    async def test():
        results = await buscar_criativos_facebook("luminária solar", "fast")
        print(f"Encontrados {len(results)} resultados")
        for result in results[:3]:
            print(f"- {result.ad.advertiser_name}: {result.ad.score}")
    
    asyncio.run(test())