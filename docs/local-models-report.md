# Free & Open-Source Image/Video Generation Models — Research Report

**Date:** 2026-08-28 · **For:** this project's `local` image/video providers
**Hardware targets:** RTX 4090 Laptop 16GB (CUDA) · Mac mini 32GB Apple Silicon (MPS)

---

## 1. Executive summary

| Slot | Current | Recommended upgrade (16GB laptop) | Recommended (32GB Mac) |
|---|---|---|---|
| **Image (speed)** | SDXL-Turbo ✅ | **Z-Image-Turbo** (6B, 8 steps, ~13GB) — better quality at similar speed | Z-Image-Turbo or FLUX.2 [klein] 4B |
| **Image (quality)** | — | **Qwen-Image** (20B, FP8/GGUF) — best text-in-image; FLUX.2 [dev] for photorealism (heavy) | Qwen-Image FP8 ✅, FLUX.2 [dev] ⚠️ |
| **Video** | Wan2.1-T2V-1.3B ✅ | Keep it; **HunyuanVideo 1.5** (~14GB w/ offload) as quality step-up | **Wan2.2-TI2V-5B** or HunyuanVideo 1.5 |
| **Video 40–60s+** | segment chaining | **LTX-2.x** (native up to ~20s + audio) or kie.ai cloud (Veo/Kling) | same |

Everything in this report is **free** (open weights) unless marked ☁️ hosted. All picks run on at least one of the two target machines.

---

## 2. Image generation models

### 2.1 Ranked for this project

| # | Model | Size | License | VRAM (fits 16GB?) | Strengths | Sources |
|---|---|---|---|---|---|---|
| 1 | **Z-Image-Turbo** (Alibaba Tongyi-MAI) | 6B (S3-DiT) | open weights | ~13GB FP16 ✅ (GGUF lower) | 8 inference steps; best speed-to-quality ratio 2026; diffusers + ComfyUI | [WillItRunAI](https://willitrunai.com/image-models/z-image-turbo), [Spheron](https://www.spheron.network/tools/gpu-recommender/Tongyi-MAI/Z-Image-Turbo/), [LocalAIMaster](https://localaimaster.com/blog/best-local-image-models-compared) |
| 2 | **FLUX.2 [klein]** 4B (Black Forest Labs) | 4B | **Apache 2.0** | ~8–13GB ✅ | Fastest permissive model; real-time capable | [LocalAIMaster](https://localaimaster.com/blog/best-local-image-models-compared), [ThunderCompute](https://www.thundercompute.com/blog/best-open-source-image-generation-models) |
| 3 | **Qwen-Image** (Alibaba) | 20B MMDiT | **Apache 2.0** | 40GB BF16 / ~16GB FP8 ⚠️ / ~8GB GGUF 4-bit ✅ | Best readable text inside images (EN+CN), posters/covers | [LocalAIMaster guide](https://localaimaster.com/models/qwen-image-local-guide) |
| 4 | **FLUX.2 [dev]** | 12B+ | open weights (non-commercial-leaning terms) | 24GB+ ❌ (quantized ⚠️) | Photorealism/prompt-adherence leader | [ThunderCompute](https://www.thundercompute.com/blog/best-open-source-image-generation-models), [Seven Labs](https://www.sevenlabs.site/blogs/open-source-image-generation-models-2026) |
| 5 | **Stable Diffusion 3.5** (Medium ok / Large heavy) | 2.5–8B | Stability community | ✅ Medium | Deepest LoRA/fine-tune ecosystem | [ThunderCompute](https://www.thundercompute.com/blog/best-open-source-image-generation-models) |
| 6 | **SDXL 1.0 / SDXL-Turbo** (current) | 3.5B | OpenRAIL | ✅✅ (~7GB) | Veteran; huge LoRA ecosystem; fastest on 16GB | [LocalAIMaster](https://localaimaster.com/blog/best-local-image-models-compared) |
| 7 | **HiDream-O1-Image** | 17B | **MIT** | ⚠️ quantized | Unified generation + editing | [Perplexity AI Magazine](https://perplexityaimagazine.com/ai-tools/best-open-source-image-generation-models/) |
| 8 | **HunyuanImage 3.0 / Sana (NVIDIA)** | various | open weights | ⚠️ | Strong 2026 newcomers | [SecondTalent](https://www.secondtalent.com/resources/top-open-source-ai-image-generators/) |

**Image picks**
- **Default (laptop + Mac): Z-Image-Turbo** — better quality than SDXL-Turbo at comparable speed, fits 16GB. Swap via `LOCAL_IMAGE_MODEL` (diffusers-supported).
- **When text in the image matters** (covers, infographics): **Qwen-Image** via FP8 (laptop, tight) or GGUF 4-bit; comfortable on the 32GB Mac.
- **Max photorealism**: FLUX.2 [dev] — only on the Mac (quantized) or cloud.

---

## 3. Video generation models

### 3.1 Ranked for this project

| # | Model | Size | License | VRAM | Clip spec | Notes | Sources |
|---|---|---|---|---|---|---|---|
| 1 | **Wan2.2-TI2V-5B** (Alibaba) | 5B dense | **Apache 2.0** | 24GB min w/ offload ⚠️ laptop / GGUF ~6–8GB ✅ | 720p, 24fps, 5s | T2V+I2V in one checkpoint; ~9 min/5s on a 4090 24GB; best quality-per-GB open model | [LocalAIMaster](https://localaimaster.com/blog/wan-video-generation-guide), [GPU-Servers](https://gpu-servers.co.uk/models/wan-2-2-ti2v-5b/), [SingularityByte](https://singularitybyte.com/tutorials/ai-video-generator-comparison-2026-open-source-models-tested.html), [GGUF table](https://lovableapp.org/blog/latest-text-to-video-models-huggingface-2026) |
| 2 | **HunyuanVideo 1.5** (Tencent) | 8.3B | Tencent Community ⚠️ (not Apache; **excludes EU**) | ~14GB w/ offload ✅ | up to 1080p | Strong motion physics; 2026 lightweight leader | [ThunderCompute](https://www.thundercompute.com/blog/best-open-source-ai-video-generation-models), [WillItRunAI](https://willitrunai.com/blog/hunyuanvideo-1-5-vram-requirements), [LocalAIMaster](https://localaimaster.com/blog/hunyuan-video-guide) |
| 3 | **Wan2.1-T2V-1.3B** (current) | 1.3B | **Apache 2.0** | ✅ ~8–10GB | 480p, 16fps, 5s | The only truly comfortable 16GB option; dev-grade quality | [ChatForest](https://chatforest.com/reviews/wan-2-1-alibaba-open-source-ai-video-generation/) |
| 4 | **LTX-2.x** (Lightricks) — 2.0 19B / 2.3–2.5 ~22B | 19–22B | open weights | from 16GB FP8 ⚠️ to 80GB | up to 4K, **up to ~20s native**, 50fps, **video + audio in one pass** | The long-clip + audio path; free LTX Desktop editor | [XYZEO](https://xyzeo.com/product/ltx-20-19b), [Kling2-6 guide](https://kling2-6.com/en/blog/ltx-video-realtime-comfyui-guide), [Oflight](https://www.oflight.co.jp/en/columns/ltx-2-5-requirements-vram-local-2026), [LocalAIMaster](https://localaimaster.com/blog/local-ai-video-generation) |
| 5 | **LTX-Video 0.9.5** (2B) | 2B | open weights | ✅ | 121+ frames @24fps | Lighter predecessor of LTX-2; longer native windows than Wan | [LocalAIMaster](https://localaimaster.com/blog/local-ai-video-generation) |
| 6 | **CogVideoX1.5-5B / Mochi-1 / Open-Sora 2.0 / Pyramid Flow** | 5–10B | varies | ⚠️–❌ | 5–10s | Credible but older/heavier; Open-Sora 2.0 nearly matches HunyuanVideo on VBench | [Fora Soft](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/self-hosting-hunyuanvideo-cogvideox-mochi-ltx), [ChatForest](https://chatforest.com/reviews/open-sora-2-hpc-ai-tech-200k-training-open-source-video/) |
| — | **Kling / Seedance / Hailuo (MiniMax)** | — | ❌ closed | API only | — | Cloud-only via kie.ai etc.; Kling has 4K + native audio | [ChatForest](https://chatforest.com/reviews/wan-2-1-alibaba-open-source-ai-video-generation/) |

**Video picks**
- **Laptop (16GB): stay on Wan2.1-1.3B** for the hourly autopilot cadence. Step up to **HunyuanVideo 1.5** (~14GB with offload) when you want visibly better motion — it *just* fits.
- **Mac (32GB): Wan2.2-TI2V-5B** becomes comfortable (24GB-class requirement, unified memory) and is the quality-per-GB leader; HunyuanVideo 1.5 also fine.
- **40–60s clips**: **LTX-2.x** is the only open line doing ~20s natively (plus synchronized audio) — 2–3 chained segments instead of 8–12. Or kie.ai (Veo 3.1 / Kling 3.0) for cloud quality.
- **Watch the license**: HunyuanVideo's Tencent Community License is **not valid in the EU** — if that matters to you, pick Wan (Apache 2.0).

---

## 4. Free hosted options (zero local compute)

| Option | What's free | Image | Video | Verdict | Source |
|---|---|---|---|---|---|
| **kie.ai** (already wired in this system) | Trial credits for new accounts | ✅ (gpt-image-1.5 etc.) | ✅ (Veo 3.1, Kling 3.0) | **Best hosted fallback** — credits cover a handful of videos | [bitdoze guide](https://www.bitdoze.com/kie-ai-video-generation/) |
| **fal.ai** (already wired) | No meaningful free tier | pay-per-use | pay-per-use | Use only if paying | [WorkflowLab](https://www.workflowlab.dev/compare/fal-vs-segmind) |
| **Hugging Face Inference API** | ~$0.10/month of routed inference | ~1 image/month | ❌ | Token use only — not viable for media | [AICreditMart](https://aicreditmart.com/ai-credits-providers/hugging-face-free-inference-api-credits-limits-guide-2026/) |
| **Google AI Studio** | Free tier quotas (change often) | ✅ Gemini image models | limited Veo | Worth checking current quotas for a cloud fallback | [ai-stack comparison](https://ai-stack.ai/en/gemini-omni-flash-vs-ltx-2-cloud-local-video-ai) |
| **Ollama (macOS only)** | 100% local | ✅ experimental (`x/z-image-turbo`, `x/flux2-klein`) | ❌ | On the Mac mini, image gen without diffusers at all | [Ollama blog](https://ollama.com/blog), [LocalAIMaster](https://localaimaster.com/blog/ollama-image-generation-models) |

---

## 5. Concrete actions for this system

1. **Upgrade the default image model**: set `LOCAL_IMAGE_MODEL` to Z-Image-Turbo's diffusers checkpoint — better quality than SDXL-Turbo at the same 16GB footprint. (Verify the exact HF repo id and diffusers pipeline class before switching; our `AutoPipelineForText2Image` loader needs a matching pipeline.)
2. **Keep `Wan2.1-T2V-1.3B` on the laptop**; on the Mac mini set `LOCAL_VIDEO_MODEL` to **Wan2.2-TI2V-5B** (bigger jump in quality; 32GB unified memory handles it).
3. **For 40–60s**: evaluate **LTX-2.x** as a third video provider (native ~20s + audio), or accept kie.ai credits for final posts.
4. **Add a Qwen-Image option** (FP8/GGUF) for text-heavy graphics (event covers, quote cards).
5. **Mac mini bonus**: wire Ollama's experimental `x/z-image-turbo` as an image provider there — zero extra dependencies.

*All models above are downloadable from HuggingFace; verify each LICENSE file before commercial use (HunyuanVideo notably excludes the EU).*
