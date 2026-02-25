#!/bin/bash
# Package the VASP POTCAR Skill for distribution

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$SCRIPT_DIR/vasp-potcar"
OUTPUT_FILE="$SCRIPT_DIR/vasp-potcar.zip"

# Remove old package if exists
rm -f "$OUTPUT_FILE"

# Create ZIP package
cd "$SCRIPT_DIR"
zip -r "$OUTPUT_FILE" vasp-potcar -x "*.pyc" -x "__pycache__/*" -x "*.DS_Store"

echo "Package created: $OUTPUT_FILE"
echo ""
echo "To install in Claude:"
echo "1. Go to Settings → Capabilities → Skills"
echo "2. Click 'Add Skill'"
echo "3. Select the vasp-potcar.zip file or the vasp-potcar folder"
echo "4. Enable the skill"
