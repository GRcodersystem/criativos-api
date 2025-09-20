import os
import asyncio
import logging
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from dotenv import load_dotenv
from models import SearchRequest, AdOut, SearchResponse, HealthResponse
from utils import is_marketplace, compute_score
from scraper import buscar_criativos_facebook

# Carrega variáveis de ambiente
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuração do FastAPI
app = FastAPI(
    title="Ferramenta Criativos BR",
    description="API para buscar criativos de dropshipping na Facebook Ads Library",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuração CORS
cors_origins = os.getenv('CORS_ORIGINS', 'https://localhost:3000').split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configurações da aplicação
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
MAX_PAGES = int(os.getenv('MAX_PAGES', '3'))
RETRY_LIMIT = int(os.getenv('RETRY_LIMIT', '2'))
USE_SELENIUM_FALLBACK = os.getenv('USE_SELENIUM_FALLBACK', 'false').lower() == 'true'


def filter_results(results: List[AdOut], request: SearchRequest) -> List[AdOut]:
    """Aplica filtros aos resultados"""
    filtered_results = []
    
    for result in results:
        ad = result.ad
        
        # Aplica exclusão de marketplaces
        if request.exclude_marketplaces and ad.landing_url:
            if is_marketplace(ad.landing_url):
                ad.exclusion_reason = "Marketplace"
                # Ainda inclui no resultado mas marca como excluído
                filtered_results.append(result)
                continue
        
        # Filtro de dias mínimos
        if ad.days_active < request.min_days:
            continue
        
        # Filtro de anúncios ativos mínimos
        if ad.advertiser_active_ads_est < request.min_active_ads:
            continue
        
        filtered_results.append(result)
    
    return filtered_results


def enhance_results(results: List[AdOut]) -> List[AdOut]:
    """Melhora os resultados com cálculos adicionais"""
    enhanced_results = []
    
    for result in results:
        ad = result.ad
        
        # Recalcula score com dados atualizados
        ad.score = compute_score(
            ad.advertiser_active_ads_est,
            ad.days_active,
            ad.variations_count
        )
        
        # Detecta provável dropshipping se ainda não foi detectado
        if not ad.is_probable_dropshipping and ad.landing_url:
            from utils import is_probable_dropshipping
            ad.is_probable_dropshipping = is_probable_dropshipping(ad.landing_url)
        
        enhanced_results.append(result)
    
    return enhanced_results


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Endpoint de health check"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow()
    )


@app.get("/")
async def root():
    """Endpoint raiz com informações da API"""
    return {
        "message": "Ferramenta Criativos BR - API",
        "version": "1.0.0",
        "description": "API para buscar criativos de dropshipping na Facebook Ads Library",
        "endpoints": {
            "health": "/health",
            "search": "/search",
            "docs": "/docs"
        }
    }


@app.post("/search", response_model=List[AdOut])
async def search_ads(request: SearchRequest):
    """
    Endpoint principal para buscar criativos na Facebook Ads Library
    """
    try:
        logger.info(f"Iniciando busca para: '{request.query}' com depth: {request.depth}")
        
        # Validação básica
        if not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query não pode ser vazia"
            )
        
        if len(request.query.strip()) < 2:
            raise HTTPException(
                status_code=400,
                detail="Query deve ter pelo menos 2 caracteres"
            )
        
        # Realiza busca usando Playwright (principal)
        try:
            results = await buscar_criativos_facebook(request.query, request.depth)
            
            # Verifica se precisa resolver CAPTCHA manualmente
            if results and isinstance(results[0], dict) and results[0].get("needs_manual_solve"):
                logger.warning("CAPTCHA detectado - requer intervenção manual")
                return JSONResponse(
                    status_code=200,
                    content={
                        "needs_manual_solve": True,
                        "message": results[0].get("message", "CAPTCHA detectado. Execute com headless=false e resolva manualmente.")
                    }
                )
                
        except Exception as e:
            logger.error(f"Erro com Playwright: {e}")
            
            # Fallback para Selenium se configurado
            if USE_SELENIUM_FALLBACK:
                logger.info("Tentando fallback com Selenium...")
                try:
                    from scraper_selenium import buscar_criativos_facebook_selenium
                    results = buscar_criativos_facebook_selenium(request.query, request.depth)
                except Exception as selenium_error:
                    logger.error(f"Erro com Selenium também: {selenium_error}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Erro no scraping (Playwright e Selenium): {str(e)}"
                    )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Erro no scraping: {str(e)}"
                )
        
        if not results:
            logger.info("Nenhum resultado encontrado")
            return []
        
        logger.info(f"Encontrados {len(results)} resultados brutos")
        
        # Aplica melhorias aos resultados
        enhanced_results = enhance_results(results)
        
        # Aplica filtros
        filtered_results = filter_results(enhanced_results, request)
        
        # Ordena por score (desc) e days_active (desc)
        filtered_results.sort(key=lambda x: (-x.ad.score, -x.ad.days_active))
        
        logger.info(f"Retornando {len(filtered_results)} resultados filtrados e ordenados")
        
        return filtered_results
        
    except HTTPException:
        raise
    except ValidationError as e:
        logger.error(f"Erro de validação: {e}")
        raise HTTPException(
            status_code=422,
            detail=f"Erro de validação: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Erro interno: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno do servidor: {str(e)}"
        )


@app.get("/status")
async def get_status():
    """Endpoint para verificar status e configurações da API"""
    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "headless": HEADLESS,
            "max_pages": MAX_PAGES,
            "retry_limit": RETRY_LIMIT,
            "use_selenium_fallback": USE_SELENIUM_FALLBACK,
            "cors_origins": cors_origins
        }
    }


# Tratamento de erros globais
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Erro não tratado: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "message": "Erro interno do servidor",
            "detail": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else "Contate o administrador"
        }
    )


# Middleware para logging de requests
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = datetime.utcnow()
    
    # Log da requisição
    logger.info(f"Requisição: {request.method} {request.url}")
    
    # Executa a requisição
    response = await call_next(request)
    
    # Log da resposta
    process_time = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"Resposta: {response.status_code} - Tempo: {process_time:.2f}s")
    
    return response


if __name__ == "__main__":
    import uvicorn
    
    # Para desenvolvimento local
    port = int(os.getenv("PORT", 8000))
    
    logger.info("Iniciando servidor de desenvolvimento...")
    logger.info(f"CORS origins: {cors_origins}")
    logger.info(f"Headless mode: {HEADLESS}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )