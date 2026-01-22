#!/usr/bin/env python3
# scripts/check_secrets.py
"""Pre-commit hook to detect test/weak credentials in .env files."""
import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    r"test-key",
    r"test-api-key",
    r"test-webhook-secret",
    r"dev-api-key",
    r"your-secret",
    r"your-webhook",
    r"CHANGE_ME",
    r"TODO",
    r"password123",
    r"admin",
]


def check_file(filepath: Path) -> tuple[bool, list[str]]:
    """Check a file for forbidden patterns."""
    issues = []

    try:
        content = filepath.read_text()

        for line_num, line in enumerate(content.splitlines(), 1):
            # Skip comments and empty lines
            if line.strip().startswith("#") or not line.strip():
                continue

            # Check each forbidden pattern
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(
                        f"Line {line_num}: Contains forbidden pattern '{pattern}': {line.strip()[:50]}"
                    )

    except Exception as e:
        issues.append(f"Error reading file: {e}")

    return len(issues) == 0, issues


def main():
    """Main pre-commit check."""
    if len(sys.argv) < 2:
        print("Usage: check_secrets.py <file>")
        return 0

    all_passed = True

    for filepath in sys.argv[1:]:
        path = Path(filepath)

        # Only check .env files
        if not path.name.startswith(".env"):
            continue

        # Skip .env.example and .env.production.example
        if "example" in path.name:
            continue

        passed, issues = check_file(path)

        if not passed:
            all_passed = False
            print(f"\n❌ SECURITY: Forbidden credentials detected in {filepath}")
            for issue in issues:
                print(f"   {issue}")

    if not all_passed:
        print("\n" + "=" * 80)
        print("⚠️  TEST/WEAK CREDENTIALS DETECTED")
        print("=" * 80)
        print("Never commit real secrets to git!")
        print("Generate strong secrets with:")
        print('  python -c "import secrets; print(secrets.token_urlsafe(32))"')
        print("=" * 80)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
