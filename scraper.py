import asyncio
import random
import re
from typing import List, Optional, Dict
from playwright.async_api import async_playwright, Page, Browser
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential
from utils import (
    parse_date_any, days_between, is_marketplace, is_probable_dropshipping,
    normalize_text, extract_ad_id_from_url, estimate_variations_from_text,
    clean_headline, compute_score, extract_domain
)
from models import AdData, AdOut
import logging

logger = logging.getLogger(__name__)
ua = UserAgent()


class FacebookAdsScraper:
    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        )
        
        context = await self.browser.new_context(
            user_agent=ua.random,
            viewport={'width': 1920, 'height': 1080}
        )
        
        self.page = await context.new_page()
        self.page.set_default_timeout(self.timeout)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()

    async def random_delay(self, min_delay: float = 1, max_delay: float = 3):
        """Delay aleatório para evitar detecção"""
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)

    async def check_for_captcha(self) -> bool:
        """Verifica se há CAPTCHA na página"""
        captcha_selectors = [
            '[data-testid="captcha"]',
            '.captcha',
            '#captcha',
            'iframe[src*="captcha"]',
            'iframe[src*="recaptcha"]',
            '.g-recaptcha',
            '[aria-label*="captcha" i]',
            '[aria-label*="verification" i]'
        ]
        
        for selector in captcha_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return True
            except:
                continue
        
        # Verifica texto que indica CAPTCHA
        page_content = await self.page.content()
        captcha_texts = ['captcha', 'verification', 'robot', 'human']
        return any(text in page_content.lower() for text in captcha_texts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def navigate_to_ads_library(self, query: str) -> bool:
        """Navega para a Facebook Ads Library com a query"""
        try:
            base_url = "https://www.facebook.com/ads/library/"
            
            # Parâmetros da URL
            params = {
                'active_status': 'active',
                'ad_type': 'all',
                'country': 'BR',
                'q': query,
                'sort_data[direction]': 'desc',
                'sort_data[mode]': 'relevancy_monthly_grouped'
            }
            
            param_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{base_url}?{param_string}"
            
            logger.info(f"Navegando para: {full_url}")
            
            await self.page.goto(full_url, wait_until='domcontentloaded')
            await self.random_delay(2, 4)
            
            # Verifica se há CAPTCHA
            if await self.check_for_captcha():
                logger.warning("CAPTCHA detectado!")
                return False
            
            # Aguarda carregamento dos resultados
            await self.page.wait_for_selector('[role="main"]', timeout=10000)
            await self.random_delay(1, 2)
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao navegar para Ads Library: {e}")
            return False

    async def scroll_and_load(self, depth: str = "standard") -> None:
        """Faz scroll para carregar mais anúncios conforme a profundidade"""
        scroll_counts = {
            "fast": 2,
            "standard": 5,
            "deep": 10
        }
        
        scroll_count = scroll_counts.get(depth, 5)
        
        for i in range(scroll_count):
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            await self.random_delay(1, 3)
            
            # A cada 3 scrolls, pausa um pouco mais
            if i % 3 == 0 and i > 0:
                await self.random_delay(2, 4)

    async def extract_ad_data(self, ad_element) -> Optional[AdData]:
        """Extrai dados de um único anúncio"""
        try:
            ad_data = AdData()
            
            # Nome do anunciante
            try:
                advertiser_elem = await ad_element.query_selector('[data-testid="page-name-link"], [role="link"][aria-label*="Page"]')
                if advertiser_elem:
                    ad_data.advertiser_name = normalize_text(await advertiser_elem.inner_text())
                    ad_data.advertiser_url = await advertiser_elem.get_attribute('href')
            except:
                pass
            
            # Headline/Título
            try:
                headline_selectors = [
                    '[data-testid="ad-title"]',
                    '[role="heading"]',
                    'h3',
                    '.ad-creative-title'
                ]
                for selector in headline_selectors:
                    headline_elem = await ad_element.query_selector(selector)
                    if headline_elem:
                        headline = await headline_elem.inner_text()
                        if headline and len(headline.strip()) > 5:
                            ad_data.headline = clean_headline(headline)
                            break
            except:
                pass
            
            # Texto do anúncio
            try:
                text_selectors = [
                    '[data-testid="ad-text"]',
                    '.userContent',
                    '[role="article"] p',
                    '.ad-creative-body'
                ]
                for selector in text_selectors:
                    text_elem = await ad_element.query_selector(selector)
                    if text_elem:
                        text = await text_elem.inner_text()
                        if text and len(text.strip()) > 10:
                            ad_data.text = normalize_text(text)
                            break
            except:
                pass
            
            # URL de landing
            try:
                link_selectors = [
                    'a[href*="l.facebook.com"]',
                    'a[data-testid="ad-link"]',
                    'a[role="link"]:not([aria-label*="Page"])'
                ]
                for selector in link_selectors:
                    link_elem = await ad_element.query_selector(selector)
                    if link_elem:
                        href = await link_elem.get_attribute('href')
                        if href and ('l.facebook.com' in href or 'http' in href):
                            ad_data.landing_url = href
                            break
            except:
                pass
            
            # Data de início (procura por texto "Ad started")
            try:
                date_selectors = [
                    '[aria-label*="started"]',
                    'span:has-text("started")',
                    'span:has-text("iniciou")',
                    '.ad-creation-date'
                ]
                for selector in date_selectors:
                    date_elem = await ad_element.query_selector(selector)
                    if date_elem:
                        date_text = await date_elem.inner_text()
                        if date_text:
                            parsed_date = parse_date_any(date_text)
                            if parsed_date:
                                ad_data.start_date = parsed_date
                                ad_data.days_active = days_between(parsed_date)
                                break
            except:
                pass
            
            # Tipo de mídia
            try:
                if await ad_element.query_selector('video'):
                    ad_data.media_type = "video"
                elif await ad_element.query_selector('img'):
                    ad_data.media_type = "image"
            except:
                pass
            
            # URL do resultado na Ads Library
            try:
                current_url = self.page.url
                ad_data.ad_library_result_url = current_url
            except:
                pass
            
            # Estima variações baseado no texto
            if ad_data.text or ad_data.headline:
                text_for_analysis = f"{ad_data.text or ''} {ad_data.headline or ''}"
                ad_data.variations_count = estimate_variations_from_text(text_for_analysis)
            
            # Detecta provável dropshipping
            if ad_data.landing_url:
                ad_data.is_probable_dropshipping = is_probable_dropshipping(ad_data.landing_url)
            
            return ad_data
            
        except Exception as e:
            logger.error(f"Erro ao extrair dados do anúncio: {e}")
            return None

    async def estimate_advertiser_active_ads(self, advertiser_url: str) -> int:
        """Estima número de anúncios ativos do anunciante"""
        if not advertiser_url:
            return 0
        
        try:
            # Abre nova aba para não perder a página atual
            new_page = await self.browser.new_page()
            
            # Constrói URL da página do anunciante na Ads Library
            if 'facebook.com' in advertiser_url:
                page_id_match = re.search(r'/(\d+)/?', advertiser_url)
                if page_id_match:
                    page_id = page_id_match.group(1)
                    ads_url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&view_all_page_id={page_id}"
                    
                    await new_page.goto(ads_url, timeout=15000)
                    await asyncio.sleep(2)
                    
                    # Tenta encontrar contador de anúncios
                    count_selectors = [
                        '[data-testid="results-count"]',
                        '.ads-library-results-count',
                        'span:has-text("results")',
                        'span:has-text("resultados")'
                    ]
                    
                    for selector in count_selectors:
                        count_elem = await new_page.query_selector(selector)
                        if count_elem:
                            count_text = await count_elem.inner_text()
                            numbers = re.findall(r'\d+', count_text.replace(',', '').replace('.', ''))
                            if numbers:
                                await new_page.close()
                                return min(int(numbers[0]), 500)  # Limita a 500
            
            await new_page.close()
            return 0
            
        except Exception as e:
            logger.error(f"Erro ao estimar anúncios ativos: {e}")
            return 0

    async def scrape_ads(self, query: str, depth: str = "standard") -> List[AdData]:
        """Método principal para fazer scraping dos anúncios"""
        ads_data = []
        
        try:
            # Navega para a Ads Library
            if not await self.navigate_to_ads_library(query):
                logger.error("Falha ao navegar para Ads Library")
                return ads_data
            
            # Faz scroll para carregar mais anúncios
            await self.scroll_and_load(depth)
            
            # Seleciona containers de anúncios
            ad_selectors = [
                '[data-testid="political_ad"]',
                '[role="article"]',
                '.ad-library-result',
                '[data-pagelet*="ad"]'
            ]
            
            ads_found = []
            for selector in ad_selectors:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    ads_found.extend(elements)
                    break
            
            if not ads_found:
                logger.warning("Nenhum anúncio encontrado com os seletores disponíveis")
                return ads_data
            
            logger.info(f"Encontrados {len(ads_found)} anúncios para processar")
            
            # Processa cada anúncio
            for i, ad_element in enumerate(ads_found[:50]):  # Limita a 50 anúncios
                try:
                    ad_data = await self.extract_ad_data(ad_element)
                    if ad_data:
                        # Estima anúncios ativos do anunciante (apenas para alguns)
                        if i < 10 and ad_data.advertiser_url:  # Apenas para os primeiros 10
                            ad_data.advertiser_active_ads_est = await self.estimate_advertiser_active_ads(
                                ad_data.advertiser_url
                            )
                        
                        ads_data.append(ad_data)
                        
                    # Delay entre anúncios
                    if i % 5 == 0:
                        await self.random_delay(1, 2)
                        
                except Exception as e:
                    logger.error(f"Erro ao processar anúncio {i}: {e}")
                    continue
            
            logger.info(f"Processados {len(ads_data)} anúncios com sucesso")
            
        except Exception as e:
            logger.error(f"Erro durante scraping: {e}")
        
        return ads_data


async def buscar_criativos_facebook(descricao_produto: str, depth: str = "standard") -> List[AdOut]:
    """
    Função principal compatível com interface existente
    """
    results = []
    
    try:
        async with FacebookAdsScraper(headless=True) as scraper:
            # Verifica CAPTCHA logo no início
            if await scraper.check_for_captcha():
                return [{"needs_manual_solve": True, "message": "CAPTCHA detectado"}]
            
            ads_data = await scraper.scrape_ads(descricao_produto, depth)
            
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
    async def test():
        results = await buscar_criativos_facebook("luminária solar", "fast")
        print(f"Encontrados {len(results)} resultados")
        for result in results[:3]:
            print(f"- {result.ad.advertiser_name}: {result.ad.score}")
    
    asyncio.run(test())