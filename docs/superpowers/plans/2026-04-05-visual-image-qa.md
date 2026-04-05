# Visual Image QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multimodal quality gate for generated images so the pipeline keeps only images that match the prompt, retries with stronger models when needed, and discards an image after three failed attempts.

**Architecture:** Split image production into two explicit phases: generation and visual review. `CapabilityRouter` will expose a model-specific image generation path plus a multimodal review path that prefers native host capabilities and falls back to Gemini vision. `VisualistAgent` will own the retry loop, prompt refinement, and discard behavior so the rest of the pipeline stays unchanged.

**Tech Stack:** Python, existing `CapabilityRouter`, Gemini multimodal API fallback, pytest-style unit tests.

---

### Task 1: Add failing tests for image QA retry and discard behavior

**Files:**
- Create: `test_visualist_quality_gate.py`
- Modify: `test_capability_router.py`

- [ ] **Step 1: Write the failing test**

```python
class QualityRouter:
    def __init__(self):
        self.calls = []

    def call_llm(self, *args, **kwargs):
        return "Create a clean cover prompt"

    def generate_image(self, prompt, aspect_ratio="1:1", model=None):
        self.calls.append(("generate", model, prompt, aspect_ratio))
        return f"{model or 'default'}".encode("utf-8")

    def review_image(self, prompt, image_bytes, aspect_ratio="1:1", title="", topic="", image_role="cover"):
        self.calls.append(("review", image_bytes.decode("utf-8"), image_role))
        return {"approved": image_bytes == b"gemini-2.5-flash-image", "reason": "too generic"}

def test_visualist_upgrades_model_until_review_passes(tmp_path):
    ...

def test_visualist_discards_image_after_three_failed_reviews(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_visualist_quality_gate.py`
Expected: FAIL because `VisualistAgent` does not yet review images or discard failed ones.

- [ ] **Step 3: Add router-level review support test**

```python
def test_review_image_uses_native_runtime_when_available():
    ...
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 test_capability_router.py`
Expected: FAIL because `CapabilityRouter.review_image()` does not exist yet.

### Task 2: Implement multimodal review in `CapabilityRouter`

**Files:**
- Modify: `capabilities.py`
- Modify: `test_capability_router.py`

- [ ] **Step 1: Write the minimal implementation**

```python
def review_image(self, prompt: str, image_bytes: bytes, aspect_ratio: str = "1:1", image_role: str = "cover", title: str = "", topic: str = "") -> Dict[str, Any]:
    ...
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python3 test_capability_router.py`
Expected: PASS for native-runtime preference and Gemini fallback.

### Task 3: Add retry-and-discard logic to `VisualistAgent`

**Files:**
- Modify: `agents.py`
- Modify: `test_visualist_quality_gate.py`

- [ ] **Step 1: Implement model-by-model attempts**

```python
approved = self.capabilities.review_image(...)
if approved:
    save_bytes(...)
else:
    try_next_model(...)
```

- [ ] **Step 2: Run the new visual tests**

Run: `python3 test_visualist_quality_gate.py`
Expected: PASS with one test proving escalation to the next model and one proving discard after three failures.

### Task 4: Update docs and verify the whole image path

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Document the new review gate and retry policy**

```markdown
Images are now generated with a visual QA gate. Each image is reviewed by a multimodal model; if it fails, the next model in `GEMINI_IMAGE_MODEL_PRIORITY` is tried. After three failed attempts, the image is omitted from the draft.
```

- [ ] **Step 2: Run the full relevant test set**

Run:
`python3 test_visualist_quality_gate.py && python3 test_capability_router.py && python3 test_gemini_text_fallback.py && python3 test_wechat_title_limit.py`

Expected: PASS.
