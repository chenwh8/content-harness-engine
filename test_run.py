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
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "WECHAT_APP_ID": os.environ.get("WECHAT_APP_ID"),
        "WECHAT_APP_SECRET": os.environ.get("WECHAT_APP_SECRET"),
    }
    
    logger.info("Initializing Orchestrator...")
    engine = Orchestrator(config)
    
    # Simulate Feishu input
    user_input = (
        "帮我写一篇关于『傅里叶分析进阶』的深度技术文章，发布到微信公众号。"
        "读者对傅里叶分析有一定基础，但卡在进阶。"
        "请用一条主线将以下内容串联起来："
        "1. 周期函数的傅里叶级数展开；"
        "2. 连续时间的傅里叶变换（CTFT），展示傅里叶变换的真正内涵；"
        "3. 离散傅里叶变换（DFT）；"
        "4. 周期/离散、连续/非周期的对偶性；"
        "5. 时域相乘与频域卷积的对偶性；"
        "6. 对底层数学公式的本质性推导。"
        "要求逻辑清晰、不失细节，语言严谨但不失可读性，适当使用 LaTeX 公式。"
    )
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
