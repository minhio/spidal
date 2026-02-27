.PHONY: uv

.PHONY: uv
uv:
	@echo "Syncing uv dependencies..."
	uv sync --all-groups --all-packages
