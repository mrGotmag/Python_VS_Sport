import uvicorn

if __name__ == "__main__":
    # 0.0.0.0 позволяет подключаться с других устройств в той же сети
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)