# openshift-metrics Makefile

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
TOOLS_BIN_DIR := $(ROOT_DIR)/bin
MCPCHECKER := $(TOOLS_BIN_DIR)/mcpchecker
MCPCHECKER_VERSION ?= 0.0.18
MCPCHECKER_OS := $(shell uname -s | tr '[:upper:]' '[:lower:]')
MCPCHECKER_ARCH := $(shell uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
MCPCHECKER_EVAL_DIR := evals/mcpchecker
EVAL_CONFIG ?= eval.yaml
RUNS ?= 1
# Keep telemeter parallel low by default (rate limits).
PARALLEL ?= 2

.PHONY: help
help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-28s %s\n", $$1, $$2}'

$(TOOLS_BIN_DIR):
	mkdir -p $(TOOLS_BIN_DIR)

$(MCPCHECKER): | $(TOOLS_BIN_DIR)
	@echo "==> Installing mcpchecker v$(MCPCHECKER_VERSION) ($(MCPCHECKER_OS)/$(MCPCHECKER_ARCH))..."
	@curl -fsSL -o $(TOOLS_BIN_DIR)/mcpchecker.zip \
		https://github.com/mcpchecker/mcpchecker/releases/download/v$(MCPCHECKER_VERSION)/mcpchecker-$(MCPCHECKER_OS)-$(MCPCHECKER_ARCH).zip
	@unzip -o -q $(TOOLS_BIN_DIR)/mcpchecker.zip -d $(TOOLS_BIN_DIR)
	@rm -f $(TOOLS_BIN_DIR)/mcpchecker.zip
	@chmod +x $(TOOLS_BIN_DIR)/mcpchecker
	@echo "✓ mcpchecker v$(MCPCHECKER_VERSION) installed"

.PHONY: install-mcpchecker
install-mcpchecker: $(MCPCHECKER) ## Install mcpchecker CLI into ./bin

.PHONY: test
test: ## Run unit tests
	PYTHONPATH=src python -m pytest tests/ -q

.PHONY: smoke
smoke: ## Run MCP smoke test (catalog always; Telemeter if .env configured)
	PYTHONPATH=src python scripts/smoke_test_mcp.py

.PHONY: run-mcpchecker-eval
run-mcpchecker-eval: $(MCPCHECKER) ## Run mcpchecker eval (TASK=… CATEGORY=… EVAL_CONFIG=… RUNS=…)
	@chmod +x $(MCPCHECKER_EVAL_DIR)/run-mcp-stdio.sh
ifdef TASK
	cd $(MCPCHECKER_EVAL_DIR) && $(MCPCHECKER) check $(EVAL_CONFIG) --run "$(TASK)" --runs $(RUNS) --verbose
else ifdef CATEGORY
	cd $(MCPCHECKER_EVAL_DIR) && $(MCPCHECKER) check $(EVAL_CONFIG) --label-selector "category=$(CATEGORY)" --runs $(RUNS) --parallel $(PARALLEL)
else
	cd $(MCPCHECKER_EVAL_DIR) && $(MCPCHECKER) check $(EVAL_CONFIG) --runs $(RUNS) --parallel $(PARALLEL)
endif

.PHONY: summary-mcpchecker-eval
summary-mcpchecker-eval: $(MCPCHECKER) ## Summarize latest mcpchecker JSON output in evals/mcpchecker/
	@out=$$(ls -t $(MCPCHECKER_EVAL_DIR)/mcpchecker-*-out.json 2>/dev/null | head -1); \
	if [ -z "$$out" ]; then echo "No mcpchecker-*-out.json found under $(MCPCHECKER_EVAL_DIR)"; exit 1; fi; \
	echo "Summarizing $$out"; \
	$(MCPCHECKER) result summary "$$out"
