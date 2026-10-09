"""Build the checked-in class/subject catalog and original starter questions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from db.seed import SUBJECT_PACKS_DIRECTORY


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


CURRICULUM: dict[str, dict[str, list[str]]] = {
    "Class 1": {
        "English": ["Two Little Hands", "Greetings", "Picture Reading", "The Cap-seller and the Monkeys", "A Visit to the Market"],
        "Mathematics": ["Finding the Furry Cat!", "What Is Long?", "Mango Treat", "Making 10", "How Many"],
        "Environmental Studies": ["My Family", "My Body", "Food Around Us", "Water Around Us", "Plants Around Us"],
        "Hindi": ["भाषा और ध्वनि", "शब्द पहचान", "चित्र वर्णन", "कविता पाठ", "सरल वाक्य"],
        "Telugu": ["అక్షరాలు", "పదాలు", "చిత్ర వివరణ", "చిన్న పద్యాలు", "సరళ వాక్యాలు"],
    },
    "Class 2": {
        "English": ["My Bicycle", "Picture Reading", "The Big Race", "Seeing without Seeing", "The Magic Porridge Pot"],
        "Mathematics": ["What Is Long?", "Counting in Groups", "How Much Can You Carry?", "Counting in Tens", "Patterns"],
        "Environmental Studies": ["Our Neighbourhood", "Food and Health", "Water and Weather", "Animals Around Us", "Travel and Communication"],
        "Hindi": ["मात्राएँ", "शब्द और वाक्य", "कहानी समझना", "कविता और लय", "चित्र से लेखन"],
        "Telugu": ["గుణింతాలు", "పద నిర్మాణం", "కథా అవగాహన", "పద్య లయ", "చిత్ర రచన"],
    },
    "Class 3": {
        "English": ["Colours", "Badal and Moti", "Best Friends", "Out in the Garden", "Talking Toys"],
        "Mathematics": ["Where to Look From", "Fun with Numbers", "Give and Take", "Long and Short", "Shapes and Designs"],
        "Environmental Studies": ["Poonam's Day out", "The Plant Fairy", "Water O' Water!", "Our First School", "Families can be Different"],
        "Hindi": ["शब्द भंडार", "संज्ञा और क्रिया", "अनुच्छेद पठन", "कविता बोध", "संवाद लेखन"],
        "Telugu": ["పద సంపద", "నామవాచకం క్రియ", "పఠన అవగాహన", "పద్య భావం", "సంభాషణ రచన"],
    },
    "Class 4": {
        "English": ["Wake Up!", "Neha's Alarm Clock", "The Little Fir Tree", "The Donkey", "The Milkman's Cow"],
        "Mathematics": ["Building with Bricks", "Long and Short", "A Trip to Bhopal", "Tick-Tick-Tick", "The Way the World Looks"],
        "Environmental Studies": ["Going to School", "Ear to Ear", "A Day with Nandu", "The Story of Amrita", "Anita and the Honeybees"],
        "Hindi": ["वर्ण और शब्द", "वचन और लिंग", "कहानी का सार", "कविता की भाषा", "पत्र लेखन"],
        "Telugu": ["వర్ణమాల పదాలు", "వచనం లింగం", "కథ సారాంశం", "పద్య భాష", "లేఖ రచన"],
    },
    "Class 5": {
        "English": ["Ice-cream Man", "Wonderful Waste!", "Teamwork", "Flying Together", "My Shadow"],
        "Mathematics": ["The Fish Tale", "Shapes and Angles", "How Many Squares?", "Parts and Wholes", "Does it Look the Same?"],
        "Environmental Studies": ["Super Senses", "A Snake Charmer's Story", "From Tasting to Digesting", "Mangoes Round the Year", "Seeds and Seeds"],
        "Hindi": ["संधि और समास परिचय", "काल और सर्वनाम", "पाठ विश्लेषण", "कविता रस", "रचनात्मक लेखन"],
        "Telugu": ["పద నిర్మాణ పరిచయం", "కాలాలు సర్వనామాలు", "పాఠ విశ్లేషణ", "పద్య రసం", "సృజనాత్మక రచన"],
    },
    "Class 6": {
        "English": ["Who Did Patrick's Homework?", "How the Dog Found Himself a New Master!", "Taro's Reward", "An Indian-American Woman in Space", "A Different Kind of School"],
        "Mathematics": ["Patterns in Mathematics", "Lines and Angles", "Number Play", "Data Handling and Presentation", "Prime Time", "Perimeter and Area", "Fractions", "Playing with Constructions", "Symmetry", "The Other Side of Zero"],
        "Science": ["The Wonderful World of Science", "Diversity in the Living World", "Mindful Eating: A Path to a Healthy Body", "Exploring Magnets", "Measurement of Length and Motion", "Materials Around Us", "Temperature and its Measurement", "A Journey through States of Water", "Methods of Separation in Everyday Life", "Living Creatures: Exploring their Characteristics", "Nature's Treasures", "Beyond Earth"],
        "Social Science": ["Locating Places on the Earth", "Oceans and Continents", "Landforms and Life", "Timeline and Sources of History", "India That Is Bharat", "The Beginnings of Indian Civilisation", "Family and Community", "Grassroots Democracy", "Culture and Knowledge Traditions"],
        "Hindi": ["वह चिड़िया जो", "बचपन", "नादान दोस्त", "चाँद से थोड़ी-सी गप्पें", "साथी हाथ बढ़ाना"],
        "Telugu": ["చదవడం మరియు భావగ్రహణం", "పద సంపద", "కథా పఠనం", "పద్య అవగాహన", "వ్యాకరణ పునాది"],
    },
    "Class 7": {
        "English": ["Three Questions", "A Gift of Chappals", "Gopal and the Hilsa-fish", "The Ashes That Made Trees Bloom", "Quality"],
        "Mathematics": ["Large Numbers Around Us", "Arithmetic Expressions", "A Peek Beyond the Point", "Expressions Using Letter-Numbers", "Parallel and Intersecting Lines", "Number Play", "A Tale of Three Intersecting Lines", "Working with Fractions", "Ratio and Proportion", "Algebraic Thinking"],
        "Science": ["The Ever-Evolving World of Science", "The Invisible Living World", "Health: The Ultimate Treasure", "Electricity: Circuits and their Components", "The World of Metals and Non-metals", "Changes Around Us", "Transport of Substances in Plants and Animals", "How Nature Works in Harmony", "Life Processes in Animals", "Life Processes in Plants", "Light: Shadows and Reflections", "Earth, Moon, and the Sun"],
        "Social Science": ["Understanding the Past", "New Beginnings and Empires", "The Rise of Kingdoms", "Political Formations in India", "The Atmosphere", "Water", "Tropical and Subtropical Regions", "The Constitution of India", "From the Rulers to the Ruled"],
        "Hindi": ["हम पंछी उन्मुक्त गगन के", "दादी माँ", "हिमालय की बेटियाँ", "कठपुतली", "मिठाईवाला"],
        "Telugu": ["కథా పఠనం", "కవితా భావం", "పాత్రల విశ్లేషణ", "పద నిర్మాణం", "వ్యాకరణ వినియోగం"],
    },
    "Class 8": {
        "English": ["The Best Christmas Present in the World", "The Tsunami", "Glimpses of the Past", "Bepin Choudhury's Lapse of Memory", "The Summit Within"],
        "Mathematics": ["A Square and A Cube", "Power Play", "A Story of Numbers", "Quadrilaterals", "Number Play", "We Distribute, Yet Things Multiply", "Proportional Reasoning", "Fractions in Disguise", "The Data Game", "Exploring Some Geometric Themes"],
        "Science": ["Exploring the Investigative World of Science", "The Invisible Living World", "Health: The Ultimate Treasure", "Electricity: Magnetic and Heating Effects", "Exploring Forces", "Pressure, Winds, Storms, and Cyclones", "Particulate Nature of Matter", "Nature of Matter: Elements, Compounds, and Mixtures", "The Amazing World of Solutes, Solvents, and Solutions", "Light: Mirrors and Lenses", "Keeping Time with the Skies", "How Nature Works in Harmony", "Our Home: Earth, a Unique Life-Sustaining Planet"],
        "Social Science": ["Natural Resources and their Use", "Landforms and Life", "The Rise of Empires", "The Age of Reorganisation", "The Constitution of India", "From the Rulers to the Ruled", "Factors of Production", "Markets Around Us"],
        "Hindi": ["ध्वनि", "लाख की चूड़ियाँ", "बस की यात्रा", "दीवानों की हस्ती", "चिट्ठियों की अनूठी दुनिया"],
        "Telugu": ["గద్య పఠనం", "కవితా పఠనం", "వ్యాస రచన", "సంభాషణ మరియు నాటకం", "భాషా నిర్మాణం"],
    },
    "Class 9": {
        "English": ["The Fun They Had", "The Sound of Music", "The Little Girl", "A Truly Beautiful Mind", "The Snake and the Mirror"],
        "Mathematics": ["Number Systems", "Polynomials", "Coordinate Geometry", "Linear Equations in Two Variables", "Introduction to Euclid's Geometry", "Lines and Angles", "Triangles", "Quadrilaterals", "Circles", "Heron's Formula", "Surface Areas and Volumes", "Statistics"],
        "Science": ["Matter in Our Surroundings", "Is Matter Around Us Pure?", "Atoms and Molecules", "Structure of the Atom", "The Fundamental Unit of Life", "Tissues", "Motion", "Force and Laws of Motion", "Gravitation", "Work and Energy", "Sound", "Improvement in Food Resources"],
        "Social Science": ["The French Revolution", "Socialism in Europe and the Russian Revolution", "India: Size and Location", "Physical Features of India", "What Is Democracy? Why Democracy?", "Constitutional Design", "The Story of Village Palampur", "People as Resource"],
        "Hindi": ["दो बैलों की कथा", "ल्हासा की ओर", "उपभोक्तावाद की संस्कृति", "साँवले सपनों की याद", "नाना साहब की पुत्री"],
        "Telugu": ["గద్యాంశ విశ్లేషణ", "కవితా విశ్లేషణ", "వ్యాకరణం మరియు ప్రయోగం", "సృజనాత్మక రచన", "వాదనాత్మక రచన"],
    },
    "Class 10": {
        "English": ["A Letter to God", "Nelson Mandela: Long Walk to Freedom", "Two Stories about Flying", "From the Diary of Anne Frank", "The Hundred Dresses"],
        "Mathematics": ["Real Numbers", "Polynomials", "Pair of Linear Equations in Two Variables", "Quadratic Equations", "Arithmetic Progressions", "Triangles", "Coordinate Geometry", "Introduction to Trigonometry", "Some Applications of Trigonometry", "Circles", "Areas Related to Circles", "Surface Areas and Volumes", "Statistics", "Probability"],
        "Science": ["Chemical Reactions and Equations", "Acids, Bases and Salts", "Metals and Non-metals", "Carbon and its Compounds", "Life Processes", "Control and Coordination", "How do Organisms Reproduce?", "Heredity", "Light: Reflection and Refraction", "The Human Eye and the Colourful World", "Electricity", "Magnetic Effects of Electric Current", "Our Environment"],
        "Social Science": ["The Rise of Nationalism in Europe", "Nationalism in India", "The Making of a Global World", "Resources and Development", "Forest and Wildlife Resources", "Water Resources", "Power Sharing", "Federalism", "Development", "Sectors of the Indian Economy"],
        "Hindi": ["सूरदास के पद", "राम-लक्ष्मण-परशुराम संवाद", "आत्मकथ्य", "उत्साह और अट नहीं रही", "नेताजी का चश्मा"],
        "Telugu": ["గద్య రచన", "పద్య భావ విశ్లేషణ", "వ్యాకరణం మరియు వాక్య నిర్మాణం", "సృజనాత్మక రచన", "సాహిత్య విమర్శ పరిచయం"],
    },
}

COLLEGE: dict[str, list[str]] = {
    "Database Management Systems": ["Database Basics", "Relational Model", "SQL Basics", "Normalization", "Transactions"],
    "Data Mining": ["Data Preprocessing", "Association Rules", "Classification", "Clustering", "Evaluation Metrics", "Data Visualization"],
    "Data Structures": ["Algorithm Analysis", "Arrays and Strings", "Linked Lists", "Stacks and Queues", "Trees and Binary Search Trees", "Heaps and Priority Queues", "Hashing", "Graphs and Traversal", "Sorting and Searching"],
    "Operating Systems": ["Operating System Structures", "Processes and Threads", "CPU Scheduling", "Process Synchronization", "Deadlocks", "Memory Management", "Virtual Memory", "File Systems", "I/O Systems"],
    "Computer Networks": ["Network Models and Protocols", "Physical Layer", "Data Link Layer", "Medium Access Control", "Network Layer and IP", "Routing", "Transport Layer", "Application Layer", "Network Security Basics"],
    "Machine Learning": ["Learning Problems and Data", "Data Preparation", "Linear Regression", "Classification Models", "Decision Trees", "Model Evaluation", "Clustering", "Neural Network Basics", "Regularization and Generalization"],
    "Python Programming": ["Python Values and Types", "Expressions and Operators", "Conditions and Loops", "Functions and Scope", "Sequences and Dictionaries", "Files and Exceptions", "Modules and Packages", "Classes and Objects", "Testing and Debugging"],
    "Discrete Mathematics": ["Logic and Propositions", "Predicates and Quantifiers", "Sets and Set Operations", "Functions and Relations", "Proof Techniques", "Counting Principles", "Recurrence Relations", "Graphs and Trees", "Boolean Algebra"],
    "Probability and Statistics": ["Data Summaries", "Counting and Probability", "Conditional Probability", "Random Variables", "Probability Distributions", "Expectation and Variance", "Sampling and Estimation", "Confidence Intervals", "Hypothesis Testing"],
    "Software Engineering": ["Software Processes", "Requirements Engineering", "System Modeling", "Software Architecture", "Design and Implementation", "Software Testing", "Project Planning", "Quality and Maintenance", "Configuration Management"],
}

STREAMS: dict[str, dict[str, list[str]]] = {
    "Science": {
        "Physics": ["Physical World and Measurement", "Kinematics", "Laws of Motion", "Work, Energy and Power", "Motion of System of Particles", "Gravitation", "Properties of Bulk Matter", "Thermodynamics", "Oscillations and Waves", "Electrostatics", "Current Electricity", "Magnetic Effects of Current", "Electromagnetic Induction", "Optics", "Dual Nature of Matter", "Atoms and Nuclei", "Electronic Devices"],
        "Chemistry": ["Some Basic Concepts of Chemistry", "Structure of Atom", "Classification of Elements", "Chemical Bonding", "States of Matter", "Thermodynamics", "Equilibrium", "Redox Reactions", "Organic Chemistry Basics", "Hydrocarbons", "Solutions", "Electrochemistry", "Chemical Kinetics", "Coordination Compounds", "Aldehydes, Ketones and Carboxylic Acids", "Biomolecules"],
        "Mathematics": ["Sets", "Relations and Functions", "Trigonometric Functions", "Complex Numbers", "Linear Inequalities", "Permutations and Combinations", "Binomial Theorem", "Sequences and Series", "Straight Lines", "Conic Sections", "Limits and Derivatives", "Statistics and Probability", "Matrices", "Determinants", "Continuity and Differentiability", "Applications of Derivatives", "Integrals", "Differential Equations", "Vectors and Three-Dimensional Geometry"],
        "Biology": ["The Living World", "Biological Classification", "Plant Kingdom", "Animal Kingdom", "Morphology of Flowering Plants", "Anatomy of Flowering Plants", "Structural Organisation in Animals", "Cell: The Unit of Life", "Biomolecules", "Cell Cycle and Cell Division", "Human Physiology", "Reproduction", "Genetics and Evolution", "Biology and Human Welfare", "Biotechnology", "Ecology"],
        "Computer Science": ["Computer Systems", "Boolean Logic", "Number Systems", "Python Fundamentals", "Conditional and Iterative Statements", "Strings and Lists", "Tuples and Dictionaries", "Functions", "File Handling", "Computer Networks", "Database Concepts", "SQL"],
    },
    "Commerce": {
        "Accountancy": ["Introduction to Accounting", "Theory Base of Accounting", "Recording of Transactions", "Bank Reconciliation", "Trial Balance and Rectification", "Depreciation and Provisions", "Financial Statements", "Accounting for Partnership", "Accounting for Companies", "Cash Flow Statement"],
        "Business Studies": ["Nature and Purpose of Business", "Forms of Business Organisation", "Public, Private and Global Enterprises", "Business Services", "Emerging Modes of Business", "Social Responsibility", "Principles of Management", "Business Environment", "Planning", "Organising", "Staffing", "Directing", "Controlling", "Financial Management", "Marketing Management"],
        "Economics": ["Introduction to Economics", "Consumer Behaviour", "Producer Behaviour", "Market Forms", "National Income", "Money and Banking", "Income Determination", "Government Budget", "Balance of Payments", "Development Experience", "Indian Economy on the Eve of Independence", "Economic Reforms", "Human Capital", "Rural Development", "Employment and Sustainable Development"],
    },
    "Arts": {
        "History": ["Writing and City Life", "An Empire Across Three Continents", "Central Islamic Lands", "The Three Orders", "Changing Cultural Traditions", "Displacing Indigenous Peoples", "Paths to Modernisation", "Bricks, Beads and Bones", "Kings, Farmers and Towns", "Kinship, Caste and Class", "Thinkers, Beliefs and Buildings", "Through the Eyes of Travellers", "Bhakti-Sufi Traditions", "An Imperial Capital: Vijayanagara", "Peasants, Zamindars and the State", "Colonialism and the Countryside", "Mahatma Gandhi and the Nationalist Movement", "Framing the Constitution"],
        "Political Science": ["Constitution: Why and How?", "Rights in the Indian Constitution", "Election and Representation", "Executive", "Legislature", "Judiciary", "Federalism", "Local Governments", "Constitution as a Living Document", "The Cold War Era", "The End of Bipolarity", "US Hegemony", "International Organisations", "Security in the Contemporary World", "Environment and Natural Resources", "Globalisation", "Challenges of Nation Building", "Era of One-Party Dominance", "Politics of Planned Development", "India's External Relations", "Democratic Resurgence", "Regional Aspirations"],
        "Geography": ["Geography as a Discipline", "The Origin and Evolution of the Earth", "Interior of the Earth", "Distribution of Oceans and Continents", "Geomorphic Processes", "Landforms and their Evolution", "Composition and Structure of Atmosphere", "Solar Radiation and Heat Balance", "Atmospheric Circulation", "Water in the Atmosphere", "World Climate and Climate Change", "Water (Oceans)", "Biodiversity and Conservation", "Population: Distribution, Density and Growth", "Migration", "Human Development", "Primary Activities", "Secondary Activities", "Tertiary and Quaternary Activities", "Transport and Communication", "International Trade"],
        "Economics": ["Introduction to Economics", "Consumer Behaviour", "Producer Behaviour", "Market Forms", "National Income", "Money and Banking", "Government Budget", "Balance of Payments", "Development Experience", "Economic Reforms"],
    },
}


def _question_set(
    topic: str,
    topic_key: str,
    count: int,
    prefix: str,
) -> list[dict[str, object]]:
    questions = []
    stems = [
        f"Which approach is most useful when beginning a problem about {topic}?",
        f"How should a learner check an answer involving {topic}?",
        f"What is a careful way to practise {topic}?",
        f"When applying {topic}, which habit supports sound reasoning?",
        f"A learner is reviewing {topic}. Which next step is most useful?",
        f"Which choice best supports learning and applying {topic}?",
    ]
    for index in range(count):
        prompt = stems[index]
        correct = f"Identify the relevant information, use the method taught for {topic}, and check the result."
        questions.append(
            {
                "key": f"{prefix}-{index + 1:03d}",
                "topic_key": topic_key,
                "difficulty": (1, 3, 5, 2, 4, 3)[index],
                "prompt": prompt,
                "options": {
                    "A": correct,
                    "B": "Ignore the conditions and select an answer without checking.",
                    "C": "Replace the given information with unrelated facts.",
                    "D": "Skip the reasoning and assume every problem has the same answer.",
                },
                "correct_answer": "A",
                "explanation": {
                    "en": f"Careful work on {topic} uses the relevant information, applies an appropriate method, and checks whether the result answers the question."
                },
            }
        )
    return questions


def _is_complete_school_pack(class_name: str, subject: str) -> bool:
    return class_name in {f"Class {grade}" for grade in range(6, 11)} and subject in {
        "Mathematics",
        "Science",
    }


def write_pack(
    root: Path,
    class_name: str,
    subject_name: str,
    topics: list[str],
    *,
    stream: str = "",
    complete: bool,
) -> None:
    stream_slug = f"{_slug(stream)}-" if stream else ""
    subject_key = (
        "dbms" if class_name == "College" and subject_name == "Database Management Systems"
        else "data-mining" if class_name == "College" and subject_name == "Data Mining"
        else f"{_slug(class_name)}-{stream_slug}{_slug(subject_name)}"
    )
    target = root / class_name
    if stream:
        target /= stream
    target /= _slug(subject_name)
    target.mkdir(parents=True, exist_ok=True)
    topic_path = target / "topics.json"
    if subject_key in {"dbms", "data-mining"} and topic_path.is_file():
        topic_catalog = json.loads(topic_path.read_text(encoding="utf-8"))
        topic_catalog["subject"]["stream"] = stream
        topic_rows = topic_catalog["topics"]
    else:
        topic_rows = []
        for index, name in enumerate(topics, start=1):
            topic_key = _slug(name) or f"topic-{index:02d}"
            topic_rows.append(
                {
                    "key": topic_key,
                    "name": name,
                    "description": f"Study and practise the ideas in {name}.",
                    "prerequisites": [topic_rows[-1]["key"]] if topic_rows else [],
                    "sequence_number": index,
                }
            )
    meta = {
        "class": class_name,
        "subject": subject_name,
        "board": "University" if class_name == "College" else "NCERT",
        "language": "en",
        # Counts alone do not make generated question sets curriculum-ready.
        "status": (
            "complete"
            if subject_key in {"dbms", "data-mining"}
            else "draft"
        ),
        "version": "1.0",
    }
    if subject_key not in {"dbms", "data-mining"} or not topic_path.is_file():
        topic_catalog = {
            "subject": {
                "key": subject_key,
                "name": subject_name,
                "class_level": class_name,
                "stream": stream,
                "description": f"{class_name} {stream} {subject_name} learning pack".strip(),
            },
            "topics": topic_rows,
        }
    topic_path.write_text(
        json.dumps(topic_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    question_count = 6 if complete else 3
    questions = []
    for topic in topic_rows:
        questions.extend(
            _question_set(
                topic["name"],
                topic["key"],
                question_count,
                f"{subject_key}-{topic['key']}",
            )
        )
    existing_question_path = target / "questions.json"
    if subject_key in {"dbms", "data-mining"} and existing_question_path.exists():
        existing_questions = json.loads(existing_question_path.read_text(encoding="utf-8"))
        questions = existing_questions.get("questions", [])
    (target / "questions.json").write_text(
        json.dumps({"questions": questions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    video_path = target / "videos.json"
    existing_videos = []
    if video_path.is_file():
        catalog = json.loads(video_path.read_text(encoding="utf-8"))
        existing_videos = catalog.get("videos", [])
    current_topic_names = {topic["name"] for topic in topic_rows}
    videos_by_topic_language = {
        (video["topic"], video["language"]): video
        for video in existing_videos
        if isinstance(video, dict)
        and video.get("topic") in current_topic_names
        and video.get("language") in {"en", "te"}
    }
    videos = []
    for topic in topic_rows:
        for language in ("en", "te"):
            videos.append(
                videos_by_topic_language.get(
                    (topic["name"], language),
                    {
                        "topic": topic["name"],
                        "title": None,
                        "source": None,
                        "url": None,
                        "duration_min": None,
                        "language": language,
                        "verified": False,
                    },
                )
            )
    video_path.write_text(
        json.dumps({"videos": videos}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_curriculum(root: str | Path = SUBJECT_PACKS_DIRECTORY) -> int:
    """Write all school, stream, and college subject packs."""
    target_root = Path(root)
    total = 0
    for class_name, subjects in CURRICULUM.items():
        for subject_name, topics in subjects.items():
            write_pack(
                target_root,
                class_name,
                subject_name,
                topics,
                complete=_is_complete_school_pack(class_name, subject_name),
            )
            total += 1

    for grade in (11, 12):
        class_name = f"Class {grade}"
        for stream, subjects in STREAMS.items():
            for subject_name, topics in subjects.items():
                write_pack(
                    target_root,
                    class_name,
                    subject_name,
                    topics,
                    stream=stream,
                    complete=False,
                )
                total += 1
            write_pack(
                target_root,
                class_name,
                "English",
                CURRICULUM["Class 10"]["English"],
                stream=stream,
                complete=False,
            )
            total += 1

    for subject_name, topics in COLLEGE.items():
        write_pack(
            target_root,
            "College",
            subject_name,
            topics,
            complete=True,
        )
        total += 1
    return total


def expected_pack_directories(root: str | Path = SUBJECT_PACKS_DIRECTORY) -> set[Path]:
    """Return the complete configured matrix for validation."""
    base = Path(root)
    expected = {
        base / class_name / _slug(subject)
        for class_name, subjects in CURRICULUM.items()
        for subject in subjects
    }
    expected.update(
        base / f"Class {grade}" / stream / _slug(subject)
        for grade in (11, 12)
        for stream, subjects in STREAMS.items()
        for subject in subjects
    )
    expected.update(
        base / f"Class {grade}" / stream / "english"
        for grade in (11, 12)
        for stream in STREAMS
    )
    expected.update(base / "College" / _slug(subject) for subject in COLLEGE)
    return expected


if __name__ == "__main__":
    print(f"Wrote {build_curriculum()} subject packs under {SUBJECT_PACKS_DIRECTORY}.")
