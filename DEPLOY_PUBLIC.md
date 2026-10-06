# AttendX - Public Web Deployment

## Render
1. Upload this project to GitHub.
2. In Render, create a Blueprint from the repository.
3. Render will use `render.yaml` to create the web service and PostgreSQL database.
4. Set `SECRET_KEY` if needed; `render.yaml` generates one automatically.
5. After deploy, open the `https://...onrender.com` URL.

## Important
- The app uses Asia/Kolkata (IST).
- Faculty session close time remains required.
- Do not commit `.env` or real passwords.
- Initial Principal login in the current application is `principal` / `principal123`; change it after first login if the application supports it.
