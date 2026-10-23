"""Shared sample documents for the export golden tests (fixtures under fixtures/export)."""

from decimal import Decimal

from app.services import export_render as render

CHOICES = (("A", "1/2"), ("B", "2/4 & 3/6"), ("C", "<không có>"), ("D", "Cả A và B"))
TEACHER_ITEMS = [
    render.TeacherExamItem(
        position=1,
        stem="Phân số nào bằng một nửa?",
        choices=CHOICES,
        points=Decimal("5.00"),
        correct_key="D",
        explanation="Bí mật: 2/4 và 3/6 đều rút gọn được về 1/2.",
    ),
    render.TeacherExamItem(
        position=2,
        stem="Tính 1/3 + 1/3.\nGhi kết quả tối giản.",
        choices=(("A", "2/3"), ("B", "2/6"), ("C", "1/9")),
        points=Decimal("5.50"),
        correct_key="A",
        explanation=None,
    ),
]
LESSON_BODY = {
    "sections": [
        {
            "heading": "Mục tiêu bài học",
            "blocks": [
                {
                    "type": "objective",
                    "text": "Học sinh nhận biết được phân số bằng nhau.",
                    "citations": [
                        {"chunkId": "00000000-0000-0000-0000-000000000001", "label": "[1]"}
                    ],
                },
                {"type": "list", "text": "Rút gọn phân số", "citations": []},
            ],
        }
    ]
}


def teacher_exam():
    return render.teacher_exam_document("Kiểm tra 15 phút — Toán 6", TEACHER_ITEMS)


def student_exam():
    return render.student_exam_document("Kiểm tra 15 phút — Toán 6", TEACHER_ITEMS)


def lesson():
    return render.content_document("Giáo án: Phân số bằng nhau", LESSON_BODY, "teacher")
