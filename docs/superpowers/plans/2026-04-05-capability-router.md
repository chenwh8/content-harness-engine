# Capability Router Refactor Plan

## Goal
Refactor the content harness so native agent capabilities are preferred first, API tokens are used only as fallbacks, and every downgrade is observable.

## Scope
- Text generation
- Research/search
- Image generation
- WeChat draft publishing
- Basic capability tracing for fallback reasons

## Files
- `agents.py`
  - Introduce a capability router abstraction.
  - Route LLM, research, and image generation through native capabilities first.
  - Keep Gemini/OpenAI/Tavily as fallback providers.
- `bridge.py`
  - Route WeChat draft publishing through the capability router before falling back to the existing poster implementation.
- `wechat_poster.py`
  - Keep the direct WeChat API implementation as the last fallback.
- `orchestrator.py`
  - Capture capability trace metadata in the execution context.
- `test_capability_router.py`
  - Verify native-first precedence and fallback behavior.
- `test_openclaw_fallback.py`
  - Keep coverage for text routing fallback order.
- `test_gemini_text_fallback.py`
  - Keep coverage for Gemini text fallback.
- `test_writer_prompt.py`
  - Keep coverage for topic-aware article prompting.

## Tasks
1. Add a capability router module that can invoke native runtime methods when available and record which provider was used.
2. Update text generation to prefer native runtime, then Gemini, then OpenAI.
3. Update research and image generation to prefer native runtime hooks where present, then existing API providers.
4. Update WeChat publishing to prefer native runtime hooks where present, then existing poster API.
5. Thread capability trace data through the orchestrator context.
6. Add/adjust tests for native-first routing, fallback routing, and trace recording.
7. Run focused regression tests and a full syntax check.

## Verification
- `python3 test_capability_router.py`
- `python3 test_openclaw_fallback.py`
- `python3 test_gemini_text_fallback.py`
- `python3 test_writer_prompt.py`
- `python3 -m py_compile agents.py bridge.py orchestrator.py wechat_poster.py test_capability_router.py test_openclaw_fallback.py test_gemini_text_fallback.py test_writer_prompt.py`
