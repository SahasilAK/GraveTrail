"""Cross-platform convenience wrapper; builds only the host operating system."""
from dataforge.build import main

if __name__ == "__main__":
    main(["--target", "executable"])
