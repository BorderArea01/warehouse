import sys
import os

# Get the absolute path of the current script's directory
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the project root directory (parent of scripts)
project_root = os.path.dirname(current_dir)
# Add project root to sys.path
sys.path.append(project_root)

from src.plugins.ToAgent import ToAgent

def main():
    to_agent = ToAgent()
    response = to_agent.invoke(query="今天星期几")
    print(response)

if __name__ == "__main__":
    main()