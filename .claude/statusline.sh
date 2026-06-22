#!/bin/bash
# Claude Code status line script
# Shows: model | working directory | context remaining %

input=$(cat)

model=$(echo "$input" | jq -r '.model.display_name // "unknown"')
dir=$(echo "$input" | jq -r '.workspace.current_dir // empty')
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# Shorten the directory path to show last 2 components
if [ -n "$dir" ]; then
  # Use basename of parent + basename of current dir for a compact display
  short_dir=$(echo "$dir" | awk -F/ '{
    if (NF >= 2) print $(NF-1) "/" $NF
    else if (NF == 1) print $NF
    else print $0
  }')
else
  short_dir=""
fi

if [ -n "$remaining" ] && [ -n "$short_dir" ]; then
  printf "%s | %s | Context: %s%%" "$model" "$short_dir" "$remaining"
elif [ -n "$remaining" ]; then
  printf "%s | Context: %s%%" "$model" "$remaining"
elif [ -n "$short_dir" ]; then
  printf "%s | %s" "$model" "$short_dir"
else
  printf "%s" "$model"
fi
