import json

from django.http import HttpResponse, JsonResponse

from app.kernel import registry

from .models import DemoAnswer

DEFINITION = {"prompt": "2 + 5 = ?", "answer": 7}
LOCALE = "cs"


def play(request):
    question = registry.get("question_type", "demo.number")
    payload = question.public_payload(DEFINITION, LOCALE)
    return HttpResponse(question.render_public(payload, LOCALE))


def submit(request):
    question = registry.get("question_type", "demo.number")
    scoring = registry.get("scoring_strategy", "demo.exact")
    try:
        answer = json.loads(request.body)
        question.validate_submission(DEFINITION, answer)
    except ValueError:
        return JsonResponse({"error": "invalid answer"}, status=400)
    result = scoring.evaluate(DEFINITION, answer, {})
    DemoAnswer.objects.create(earned_points=result.earned_points)
    return JsonResponse({"earned_points": result.earned_points})
