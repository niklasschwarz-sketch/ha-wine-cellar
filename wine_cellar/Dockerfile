ARG BUILD_FROM
FROM $BUILD_FROM
RUN apk add --no-cache python3 py3-pip ca-certificates \
 && pip install --no-cache-dir --break-system-packages pg8000==1.31.2 \
 && python3 -c "import sqlite3, pg8000"
COPY app /app
RUN python3 /app/fetch_ocr.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
