"""V20.4 — Curated question bank.

Two jobs:

1. **Fallback content.** If every AI provider fails (see
   `app.ai.completion_service.CompletionError`), `question_engine.py`
   picks straight from here instead of leaving the candidate stuck —
   the same "degrade gracefully, never a raw 500" posture
   `completion_service`'s own docstring describes for
   `app.services.career_ai`.
2. **Grounding material for AI-generated questions.** Even when a
   provider is available, the category/difficulty picked by the
   (deterministic) adaptive logic in `question_engine.py` is seeded
   with 1-2 real questions from here as style/scope examples in the
   prompt, so the model phrases something in-genre rather than
   drifting.

Every entry is a plain, hand-written question — nothing here is
AI-generated, so this file is also the trustworthy fallback the
"fabricate nothing" AI-safety rule can point to when a provider is
unavailable.
"""

from __future__ import annotations

TECHNICAL_CATEGORIES = {
    "programming": {
        "easy": [
            "What is the difference between a compiled and an interpreted language?",
            "Explain the difference between pass-by-value and pass-by-reference.",
        ],
        "medium": [
            "What are the trade-offs between using recursion and iteration to solve the same problem?",
            "How does garbage collection work in a language you're comfortable with, and what are its costs?",
        ],
        "hard": [
            "Walk through how you would design a thread-safe cache with an LRU eviction policy.",
            "How would you diagnose and fix a memory leak in a long-running service?",
        ],
    },
    "dsa": {
        "easy": [
            "What is the time complexity of searching in a sorted array vs. an unsorted array?",
            "Explain the difference between a stack and a queue, with a real use case for each.",
        ],
        "medium": [
            "How would you detect a cycle in a linked list, and what's the time/space complexity of your approach?",
            "Given an array, how would you find the two numbers that sum to a target value efficiently?",
        ],
        "hard": [
            "How would you design an algorithm to find the shortest path in a weighted graph with negative edges?",
            "Explain how a balanced binary search tree maintains its balance, and why that matters for complexity.",
        ],
    },
    "oop": {
        "easy": ["What are the four pillars of object-oriented programming, and what does each mean in practice?"],
        "medium": ["When would you favor composition over inheritance, and why?"],
        "hard": ["How would you design a plugin system using interfaces/abstract classes so new plugins never require changing existing code?"],
    },
    "dbms": {
        "easy": ["What is the difference between a primary key and a foreign key?"],
        "medium": ["Explain the difference between the first three normal forms with a concrete example."],
        "hard": ["How would you design a schema and indexing strategy for a system with heavy read traffic and occasional bulk writes?"],
    },
    "os": {
        "easy": ["What is the difference between a process and a thread?"],
        "medium": ["Explain deadlock, and name two strategies to prevent it."],
        "hard": ["How does virtual memory work, and what happens on a page fault?"],
    },
    "computer_networks": {
        "easy": ["What happens, step by step, when you type a URL into a browser and press enter?"],
        "medium": ["Explain the difference between TCP and UDP, and when you'd choose one over the other."],
        "hard": ["How would you design a system to handle millions of concurrent WebSocket connections?"],
    },
    "system_design": {
        "easy": ["How would you design a URL shortener at a high level?"],
        "medium": ["How would you design a rate limiter for a public API?"],
        "hard": ["How would you design a system like a notification service that needs to handle millions of users, multiple delivery channels, and retries?"],
    },
    "cloud": {
        "easy": ["What's the difference between horizontal and vertical scaling?"],
        "medium": ["How would you design a deployment pipeline with zero-downtime releases?"],
        "hard": ["How would you design a multi-region architecture for high availability and disaster recovery?"],
    },
    "data_science": {
        "easy": ["What is the difference between supervised and unsupervised learning?"],
        "medium": ["How would you handle a dataset with significant class imbalance?"],
        "hard": ["How would you detect and address data drift in a production ML model?"],
    },
    "machine_learning": {
        "easy": ["What is overfitting, and name two ways to reduce it."],
        "medium": ["Explain the bias-variance tradeoff with a practical example."],
        "hard": ["How would you design an ML system to serve real-time predictions at low latency and monitor for model degradation?"],
    },
    "sql": {
        "easy": ["What is the difference between an INNER JOIN and a LEFT JOIN?"],
        "medium": ["Write a query (describe it verbally) to find the second-highest salary in a table without using a database-specific function."],
        "hard": ["How would you optimize a slow query that joins several large tables — what would you look at first?"],
    },
}

BEHAVIORAL_AREAS = {
    "leadership": [
        "Tell me about a time you led a project or initiative without formal authority. What did you do?",
        "Describe a situation where you had to motivate a team that was losing momentum.",
    ],
    "teamwork": [
        "Tell me about a time you worked with a difficult teammate. How did you handle it?",
        "Describe a project where cross-functional collaboration was critical to success.",
    ],
    "conflict": [
        "Tell me about a disagreement you had with a coworker or manager. How was it resolved?",
        "Describe a time your idea was rejected. How did you respond?",
    ],
    "failure": [
        "Tell me about a time you failed at something important. What did you learn?",
        "Describe a decision you made that, in hindsight, you'd make differently.",
    ],
    "problem_solving": [
        "Tell me about the most complex problem you've had to solve. Walk me through your approach.",
        "Describe a time you had to make a decision with incomplete information.",
    ],
    "communication": [
        "Tell me about a time you had to explain something technical to a non-technical audience.",
        "Describe a time you had to deliver difficult feedback or bad news.",
    ],
    "ownership": [
        "Tell me about a time you went beyond your defined role to get something done.",
        "Describe a mistake you made and how you took responsibility for it.",
    ],
    "adaptability": [
        "Tell me about a time priorities changed suddenly. How did you adjust?",
        "Describe a time you had to learn something new quickly to complete a task.",
    ],
}

HR_QUESTIONS = [
    "Walk me through your background and what's brought you to this point in your career.",
    "Why are you interested in this role / this type of work?",
    "What are you looking for in your next opportunity?",
    "Where do you see yourself in the next few years?",
    "What questions do you have for me?",
]

CODING_PROBLEMS = {
    "easy": [
        {
            "title": "Two Sum",
            "statement": "Given an array of integers and a target value, return the indices of the two numbers that add up to the target.",
            "constraints": "Exactly one valid answer exists. You may not use the same element twice.",
            "examples": "Input: [2,7,11,15], target=9 -> Output: [0,1]",
            "expected_complexity": "O(n) time, O(n) space is achievable",
        },
    ],
    "medium": [
        {
            "title": "Longest Substring Without Repeating Characters",
            "statement": "Given a string, find the length of the longest substring without repeating characters.",
            "constraints": "0 <= length <= 5 * 10^4",
            "examples": "Input: 'abcabcbb' -> Output: 3 ('abc')",
            "expected_complexity": "O(n) time is achievable with a sliding window",
        },
    ],
    "hard": [
        {
            "title": "Merge k Sorted Lists",
            "statement": "Given k sorted linked lists, merge them into one sorted list.",
            "constraints": "k can be large; lists may be empty.",
            "examples": "Input: [[1,4,5],[1,3,4],[2,6]] -> Output: [1,1,2,3,4,4,5,6]",
            "expected_complexity": "O(N log k) using a heap, where N is total elements",
        },
    ],
}

ALL_TECHNICAL_CATEGORY_KEYS = list(TECHNICAL_CATEGORIES.keys())
ALL_BEHAVIORAL_AREA_KEYS = list(BEHAVIORAL_AREAS.keys())


def sample_technical(category: str, difficulty: str, exclude: set[str]) -> str | None:
    pool = TECHNICAL_CATEGORIES.get(category, {}).get(difficulty, [])
    for q in pool:
        if q not in exclude:
            return q
    # Fall back to any difficulty in the same category before giving up.
    for tier in ("easy", "medium", "hard"):
        for q in TECHNICAL_CATEGORIES.get(category, {}).get(tier, []):
            if q not in exclude:
                return q
    return None


def sample_behavioral(area: str, exclude: set[str]) -> str | None:
    for q in BEHAVIORAL_AREAS.get(area, []):
        if q not in exclude:
            return q
    return None


def sample_hr(exclude: set[str]) -> str | None:
    for q in HR_QUESTIONS:
        if q not in exclude:
            return q
    return None


def sample_coding_problem(difficulty: str, exclude_titles: set[str]) -> dict | None:
    for problem in CODING_PROBLEMS.get(difficulty, []):
        if problem["title"] not in exclude_titles:
            return problem
    for tier in ("easy", "medium", "hard"):
        for problem in CODING_PROBLEMS.get(tier, []):
            if problem["title"] not in exclude_titles:
                return problem
    return None
