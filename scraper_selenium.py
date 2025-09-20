import time
import random
import re
from typing import List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from fake_useragent import UserAgent
from utils import (
    parse_date_any, days_between, is_marketplace, is_probable_dropshipping,
    normalize_text, extract_ad_id_from_url, estimate_variations_from_text,
    clean_headline, compute_score, extract_domain
)
from models import AdData, AdOut
import logging

logger = logging.getLogger(__name__)
ua = UserAgent()


class FacebookAdsSeleniumScraper:
    def __init__(self, headless: bool = True, timeout: int = 30):
        self.headless = headless
        self.timeout = timeout
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        
    def __enter__(self):
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-setuid-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-accelerated-2d-canvas')
        chrome_options.add_argument('--no-first-run')
        chrome_options.add_argument('--disable-default-apps')
        chrome_options.add_argument(f'--user-agent={ua.random}')
        chrome_options.add_argument('--window-size=1920,1080')
        
        # Desabilita imagens para acelerar
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.set_page_load_timeout(self.timeout)
        self.driver.implicitly_wait(10)
        self.wait = WebDriverWait(self.driver, self.timeout)
        
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()

    def random_delay(self, min_delay: float = 1, max_delay: float = 3):
        """Delay aleatório para evitar detecção"""
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def check_for_captcha(self) -> bool:
        """Verifica se há CAPTCHA na página"""
        captcha_selectors = [
            '[data-testid="captcha"]',
            '.captcha',
            '#captcha',
            'iframe[src*="captcha"]',
            'iframe[src*="recaptcha"]',
            '.g-recaptcha'
        ]
        
        for selector in captcha_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(elem.is_displayed() for elem in elements):
                    return True
            except:
                continue
        
        # Verifica texto que indica CAPTCHA
        page_source = self.driver.page_source.lower()
        captcha_texts = ['captcha', 'verification', 'robot', 'human']
        return any(text in page_source for text in captcha_texts)

    def navigate_to_ads_library(self, query: str) -> bool:
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
            
            self.driver.get(full_url)
            self.random_delay(2, 4)
            
            # Verifica se há CAPTCHA
            if self.check_for_captcha():
                logger.warning("CAPTCHA detectado!")
                return False
            
            # Aguarda carregamento dos resultados
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[role="main"]')))
            except TimeoutException:
                logger.error("Timeout aguardando carregamento da página")
                return False
            
            self.random_delay(1, 2)
            return True
            
        except Exception as e:
            logger.error(f"Erro ao navegar para Ads Library: {e}")
            return False

    def scroll_and_load(self, depth: str = "standard") -> None:
        """Faz scroll para carregar mais anúncios conforme a profundidade"""
        scroll_counts = {
            "fast": 2,
            "standard": 5,
            "deep": 10
        }
        
        scroll_count = scroll_counts.get(depth, 5)
        
        for i in range(scroll_count):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self.random_delay(1, 3)
            
            # A cada 3 scrolls, pausa um pouco mais
            if i % 3 == 0 and i > 0:
                self.random_delay(2, 4)

    def extract_ad_data(self, ad_element) -> Optional[AdData]:
        """Extrai dados de um único anúncio"""
        try:
            ad_data = AdData()
            
            # Nome do anunciante
            try:
                advertiser_selectors = [
                    '[data-testid="page-name-link"]',
                    '[role="link"][aria-label*="Page"]',
                    'a[href*="/ads/library/?active_status=active&ad_type=all&country=BR&view_all_page_id"]'
                ]
                for selector in advertiser_selectors:
                    try:
                        advertiser_elem = ad_element.find_element(By.CSS_SELECTOR, selector)
                        if advertiser_elem:
                            ad_data.advertiser_name = normalize_text(advertiser_elem.text)
                            ad_data.advertiser_url = advertiser_elem.get_attribute('href')
                            break
                    except NoSuchElementException:
                        continue
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
                    try:
                        headline_elem = ad_element.find_element(By.CSS_SELECTOR, selector)
                        if headline_elem and headline_elem.text.strip():
                            ad_data.headline = clean_headline(headline_elem.text)
                            break
                    except NoSuchElementException:
                        continue
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
                    try:
                        text_elem = ad_element.find_element(By.CSS_SELECTOR, selector)
                        if text_elem and text_elem.text.strip():
                            ad_data.text = normalize_text(text_elem.text)
                            break
                    except NoSuchElementException:
                        continue
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
                    try:
                        link_elem = ad_element.find_element(By.CSS_SELECTOR, selector)
                        if link_elem:
                            href = link_elem.get_attribute('href')
                            if href and ('l.facebook.com' in href or 'http' in href):
                                ad_data.landing_url = href
                                break
                    except NoSuchElementException:
                        continue
            except:
                pass
            
            # Data de início
            try:
                date_selectors = [
                    '[aria-label*="started"]',
                    'span[aria-label*="started"]',
                    'span[aria-label*="iniciou"]'
                ]
                for selector in date_selectors:
                    try:
                        date_elem = ad_element.find_element(By.CSS_SELECTOR, selector)
                        if date_elem:
                            date_text = date_elem.get_attribute('aria-label') or date_elem.text
                            if date_text:
                                parsed_date = parse_date_any(date_text)
                                if parsed_date:
                                    ad_data.start_date = parsed_date
                                    ad_data.days_active = days_between(parsed_date)
                                    break
                    except NoSuchElementException:
                        continue
            except:
                pass
            
            # Tipo de mídia
            try:
                if ad_element.find_elements(By.CSS_SELECTOR, 'video'):
                    ad_data.media_type = "video"
                elif ad_element.find_elements(By.CSS_SELECTOR, 'img'):
                    ad_data.media_type = "image"
            except:
                pass
            
            # URL do resultado na Ads Library
            try:
                ad_data.ad_library_result_url = self.driver.current_url
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

    def estimate_advertiser_active_ads(self, advertiser_url: str) -> int:
        """Estima número de anúncios ativos do anunciante"""
        if not advertiser_url:
            return 0
        
        try:
            original_window = self.driver.current_window_handle
            self.driver.execute_script("window.open('');")
            new_window = [handle for handle in self.driver.window_handles if handle != original_window][0]
            self.driver.switch_to.window(new_window)
            
            # Constrói URL da página do anunciante na Ads Library
            if 'facebook.com' in advertiser_url:
                page_id_match = re.search(r'/(\d+)/?', advertiser_url)
                if page_id_match:
                    page_id = page_id_match.group(1)
                    ads_url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&view_all_page_id={page_id}"
                    
                    self.driver.get(ads_url)
                    time.sleep(3)
                    
                    # Tenta encontrar contador de anúncios
                    count_selectors = [
                        '[data-testid="results-count"]',
                        '.ads-library-results-count',
                        'span:contains("results")',
                        'span:contains("resultados")'
                    ]
                    
                    for selector in count_selectors:
                        try:
                            count_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for count_elem in count_elements:
                                count_text = count_elem.text
                                if count_text:
                                    numbers = re.findall(r'\d+', count_text.replace(',', '').replace('.', ''))
                                    if numbers:
                                        self.driver.close()
                                        self.driver.switch_to.window(original_window)
                                        return min(int(numbers[0]), 500)  # Limita a 500
                        except:
                            continue
            
            self.driver.close()
            self.driver.switch_to.window(original_window)
            return 0
            
        except Exception as e:
            logger.error(f"Erro ao estimar anúncios ativos: {e}")
            try:
                self.driver.switch_to.window(original_window)
            except:
                pass
            return 0

    def scrape_ads(self, query: str, depth: str = "standard") -> List[AdData]:
        """Método principal para fazer scraping dos anúncios"""
        ads_data = []
        
        try:
            # Navega para a Ads Library
            if not self.navigate_to_ads_library(query):
                logger.error("Falha ao navegar para Ads Library")
                return ads_data
            
            # Faz scroll para carregar mais anúncios
            self.scroll_and_load(depth)
            
            # Seleciona containers de anúncios
            ad_selectors = [
                '[data-testid="political_ad"]',
                '[role="article"]',
                '.ad-library-result',
                '[data-pagelet*="ad"]'
            ]
            
            ads_found = []
            for selector in ad_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        ads_found.extend(elements)
                        break
                except:
                    continue
            
            if not ads_found:
                logger.warning("Nenhum anúncio encontrado com os seletores disponíveis")
                return ads_data
            
            logger.info(f"Encontrados {len(ads_found)} anúncios para processar")
            
            # Processa cada anúncio
            for i, ad_element in enumerate(ads_found[:50]):  # Limita a 50 anúncios
                try:
                    ad_data = self.extract_ad_data(ad_element)
                    if ad_data:
                        # Estima anúncios ativos do anunciante (apenas para alguns)
                        if i < 10 and ad_data.advertiser_url:  # Apenas para os primeiros 10
                            ad_data.advertiser_active_ads_est = self.estimate_advertiser_active_ads(
                                ad_data.advertiser_url
                            )
                        
                        ads_data.append(ad_data)
                        
                    # Delay entre anúncios
                    if i % 5 == 0:
                        self.random_delay(1, 2)
                        
                except Exception as e:
                    logger.error(f"Erro ao processar anúncio {i}: {e}")
                    continue
            
            logger.info(f"Processados {len(ads_data)} anúncios com sucesso")
            
        except Exception as e:
            logger.error(f"Erro durante scraping: {e}")
        
        return ads_data


def buscar_criativos_facebook_selenium(descricao_produto: str, depth: str = "standard") -> List[AdOut]:
    """
    Função principal compatível com interface existente usando Selenium
    """
    results = []
    
    try:
        with FacebookAdsSeleniumScraper(headless=True) as scraper:
            # Verifica CAPTCHA logo no início
            if scraper.check_for_captcha():
                return [{"needs_manual_solve": True, "message": "CAPTCHA detectado"}]
            
            ads_data = scraper.scrape_ads(descricao_produto, depth)
            
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
        logger.error(f"Erro na função buscar_criativos_facebook_selenium: {e}")
        return []


if __name__ == "__main__":
    # Teste simples
    results = buscar_criativos_facebook_selenium("luminária solar", "fast")
    print(f"Encontrados {len(results)} resultados")
    for result in results[:3]:
        print(f"- {result.ad.advertiser_name}: {result.ad.score}")