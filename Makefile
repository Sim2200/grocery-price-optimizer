PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup data demo test eval eval-llm plan app clean

setup:            ## create the virtualenv and install the package + dev deps
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

data:             ## regenerate the SYNTHETIC receipts (JSON + PNG) from a fixed seed
	$(PY) scripts/generate_synthetic_data.py

demo:             ## load the bundled synthetic receipts into a fresh SQLite DB
	$(PY) -m grocery_optimizer.cli demo --reset

plan: demo        ## plan a trip for the sample shopping list
	$(PY) -m grocery_optimizer.cli plan data/sample_shopping_list.csv --trip-cost 5

test:             ## run the unit tests (no API key needed)
	$(PY) -m pytest

eval:             ## run the extraction eval harness on the synthetic example
	$(PY) evals/extraction_eval.py --gold data/synthetic/receipts --pred evals/data/synthetic_noisy_predictions

eval-llm:      ## run real the LLM extraction on the synthetic PNGs and score it (needs ANTHROPIC_API_KEY)
	$(PY) evals/extraction_eval.py --gold data/synthetic/receipts --images data/synthetic/images --extractor llm

app:              ## start the Streamlit UI
	.venv/bin/streamlit run app/streamlit_app.py

clean:
	rm -rf data/grocery.db .pytest_cache
