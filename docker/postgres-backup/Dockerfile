# pg_dump must match the server's major version (pgvector/pgvector:pg16)
FROM postgres:16-alpine

COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY crontab /etc/crontabs/root

RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh

CMD ["/usr/local/bin/entrypoint.sh"]
