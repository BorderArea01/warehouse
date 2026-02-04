from ToAgent import ToAgent

def main():
    to_agent = ToAgent()
    response = to_agent.invoke(query="今天星期几")
    print(response)

if __name__ == "__main__":
    main()