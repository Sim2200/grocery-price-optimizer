PY := .venv/bin/python
PIP := .venv/bin/pip
UVICORN := .venv/bin/uvicorn --factory grocery_optimizer.api.app:create_app

.PHONY: setup setup-py setup-web dev api web build serve demo plan test typecheck check \
        eval eval-llm eval-matching benchmark data clean \
        docker-build docker-up docker-down

setup: setup-py setup-web  ## install everything (Python venv + frontend packages)

setup-py:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

setup-web:
	cd web && npm install

dev:              ## run API (:8000) and React dev server (:5173) together; Ctrl+C stops both
	@trap 'kill 0' INT TERM EXIT; \
	$(UVICORN) --reload --reload-dir src --port 8000 & \
	cd web && npm run dev

api:              ## API only, with auto-reload. Docs at http://localhost:8000/docs
	$(UVICORN) --reload --reload-dir src --port 8000

web:              ## React dev server only
	cd web && npm run dev

build:            ## type-check and build the frontend into web/dist
	cd web && npm run build

serve: build      ## single process: FastAPI serves the built React app at http://localhost:8000
	$(UVICORN) --port 8000

demo:             ## load the bundled SYNTHETIC receipts into data/grocery.db
	$(PY) -m grocery_optimizer.cli demo --reset

plan: demo        ## plan a trip for the sample shopping list from the terminal
	$(PY) -m grocery_optimizer.cli plan data/sample_shopping_list.csv --trip-cost 5

test:             ## Python tests (no API key needed)
	$(PY) -m pytest

typecheck:        ## TypeScript type check of the frontend
	cd web && npm run typecheck

check: test build ## everything CI would run

eval:             ## extraction eval harness on the SYNTHETIC noisy predictions (demo of the metrics)
	$(PY) evals/extraction_eval.py --gold data/synthetic/receipts --pred evals/data/synthetic_noisy_predictions

eval-llm:         ## real LLM extraction on the synthetic PNGs, scored (needs ANTHROPIC_API_KEY + GROCERY_LLM_MODEL, costs money)
	$(PY) evals/extraction_eval.py --gold data/synthetic/receipts --images data/synthetic/images --extractor llm

eval-matching:    ## product-matching accuracy on the synthetic labels, with a rules-off ablation
	$(PY) evals/matching_eval.py

benchmark:        ## optimizer vs baselines on the synthetic price DB
	$(PY) evals/optimizer_benchmark.py

data:             ## regenerate the SYNTHETIC receipts (JSON + PNG) from a fixed seed
	$(PY) scripts/generate_synthetic_data.py

docker-build:     ## build the production image (frontend + API in one container)
	docker build -t grocery-optimizer:local .

docker-up:        ## run the stack with Docker Compose (app on :8000)
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	rm -rf data/grocery.db .pytest_cache web/dist
