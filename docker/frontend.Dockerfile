FROM nginx:1.25-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our nginx config
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy frontend files
COPY frontend/ /usr/share/nginx/html/

EXPOSE 80
