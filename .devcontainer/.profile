# Add user bin directories to PATH
if [ -d "$HOME/bin" ]; then
    PATH="$HOME/bin:$PATH"
fi

if [ -d "$HOME/.local/bin" ]; then
    PATH="$HOME/.local/bin:$PATH"
fi

# Direnv hook for automatic .envrc loading
if [ -n "${ZSH_VERSION:-}" ]; then
    eval "$(direnv hook zsh)"
elif [ -n "${BASH_VERSION:-}" ]; then
    eval "$(direnv hook bash)"
fi