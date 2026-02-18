#################### Setup ####################
.PHONY: devcontainer
devcontainer: uv claude
	@echo "Running devcontainer post create script..."
	direnv allow

.PHONY: uv
uv:
	@echo "Syncing uv dependencies..."
	uv sync --all-groups --all-packages

.PHONY: claude
claude:
	@echo "Setting up Claude CLI..."
	curl -fsSL https://claude.ai/install.sh | zsh
