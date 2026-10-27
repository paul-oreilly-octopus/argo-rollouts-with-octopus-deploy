FROM python:3.13-slim
WORKDIR /app
COPY app.py .
ENV PYTHONUNBUFFERED=1
USER 65534
EXPOSE 8080
CMD ["python", "/app/app.py"]
