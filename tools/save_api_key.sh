#!/bin/zsh
# Asks for an Anthropic API key without showing it, and saves it to ~/.zshrc
# so the photo review can use it. The key never appears on screen or in history.
# It keeps asking until a key is saved, so a key is never left to be pasted at
# the shell prompt by mistake. Press Ctrl-C to give up.

while true; do
  read -rs "key?Paste your Anthropic API key, then press Return (nothing shows while you paste): "
  echo
  if [[ -z "$key" ]]; then
    echo "Nothing was pasted. Copy the key on the Claude Console page, then paste here with Cmd-V."
  elif [[ "$key" != sk-ant-* ]]; then
    echo "That doesn't look like an Anthropic API key (they start with sk-ant-). Try again."
  else
    break
  fi
done
touch ~/.zshrc
# Replace any key saved earlier rather than adding a second one.
sed -i '' '/^export ANTHROPIC_API_KEY=/d' ~/.zshrc
printf "export ANTHROPIC_API_KEY='%s'\n" "$key" >> ~/.zshrc
chmod 600 ~/.zshrc
unset key
echo "Saved. You can close this tab and tell Claude it's done."
