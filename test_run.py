import os
import logging
from dotenv import load_dotenv
from orchestrator import Orchestrator

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    # Load environment variables
    load_dotenv()
    
    # Configuration
    config = {
        "OUTPUT_DIR": os.environ.get("OUTPUT_DIR", "./output"),
        "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY")
    }
    
    logger.info("Initializing Orchestrator...")
    engine = Orchestrator(config)
    
    # Simulate Feishu input
    user_input = "帮我写一篇关于 AI Agent 框架的深度文章，发布到微信公众号和掘金，语言要专业但通俗易懂。"
    logger.info(f"Simulating user input: {user_input}")
    
    result = engine.handle_input(user_input)
    
    logger.info("\n" + "="*50)
    logger.info("Pipeline Execution Result:")
    logger.info(f"Status: {result.get('status')}")
    logger.info(f"Message: {result.get('message')}")
    
    if "files" in result:
        logger.info("\nGenerated Files:")
        for key, path in result["files"].items():
            logger.info(f"- {key}: {path}")
            
    logger.info("="*50)

if __name__ == "__main__":
    main()
