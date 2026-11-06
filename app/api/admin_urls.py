from django.urls import path

from app.api import admin_auth, admin_quizzes, admin_runs, admin_users

urlpatterns = [
    path("", admin_auth.index, name="admin_index"),
    path("login", admin_auth.login_page, name="admin_login"),
    path("logout", admin_auth.logout_page, name="admin_logout"),
    path("quizzes", admin_quizzes.quiz_list, name="admin_quizzes"),
    path("quizzes/new", admin_quizzes.quiz_new, name="admin_quiz_new"),
    path("quizzes/<uuid:quiz_id>/edit", admin_quizzes.quiz_edit, name="admin_quiz_edit"),
    path(
        "quizzes/<uuid:quiz_id>/questions/new",
        admin_quizzes.question_new,
        name="admin_question_new",
    ),
    path(
        "quizzes/<uuid:quiz_id>/questions/<str:question_id>/edit",
        admin_quizzes.question_edit,
        name="admin_question_edit",
    ),
    path(
        "quizzes/<uuid:quiz_id>/questions/<str:question_id>/delete",
        admin_quizzes.question_delete,
        name="admin_question_delete",
    ),
    path("quizzes/<uuid:quiz_id>/publish", admin_quizzes.quiz_publish, name="admin_quiz_publish"),
    path("quizzes/<uuid:quiz_id>/runs", admin_quizzes.run_open, name="admin_run_open"),
    path("quizzes/<uuid:quiz_id>/qr.svg", admin_runs.quiz_qr, name="admin_quiz_qr"),
    path("runs/<uuid:run_id>", admin_runs.run_detail, name="admin_run"),
    path("runs/<uuid:run_id>/close", admin_runs.run_close, name="admin_run_close"),
    path("users", admin_users.users, name="admin_users"),
]
