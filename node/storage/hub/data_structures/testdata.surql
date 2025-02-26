CREATE invite SET code="DZHA4ZTK";

CREATE license:apache2 SET license_type="Apache 2.0", details="https://www.apache.org/licenses/LICENSE-2.0";
CREATE license:mit SET license_type="MIT", details="https://opensource.org/licenses/MIT";

CREATE category:multimodal SET name="Multimodal";
-- subcategories for multimodal
CREATE category:feature_extraction SET name="Feature Extraction", parent_categories=[category:multimodal];
CREATE category:text_to_image SET name="Text-to-Image", parent_categories=[category:multimodal];
CREATE category:image_to_text SET name="Image-to-Text", parent_categories=[category:multimodal];
CREATE category:image_to_video SET name="Image-to-Video", parent_categories=[category:multimodal];
CREATE category:text_to_video SET name="Text-to-Video", parent_categories=[category:multimodal];
CREATE category:visual_question_answering SET name="Visual Question Answering", parent_categories=[category:multimodal];
CREATE category:document_question_answering SET name="Document Question Answering", parent_categories=[category:multimodal];
CREATE category:graph_machine_learning SET name="Graph Machine Learning", parent_categories=[category:multimodal];
CREATE category:text_to_3d SET name="Text-to-3D", parent_categories=[category:multimodal];
CREATE category:image_to_3d SET name="Image-to-3D", parent_categories=[category:multimodal];

CREATE category:computer_vision SET name="Computer Vision";
-- subcategories for computer vision
CREATE category:depth_estimation SET name="Depth Estimation", parent_categories=[category:computer_vision];
CREATE category:image_classification SET name="Image Classification", parent_categories=[category:computer_vision];
CREATE category:object_detection SET name="Object Detection", parent_categories=[category:computer_vision];
CREATE category:image_segmentation SET name="Image Segmentation", parent_categories=[category:computer_vision];
CREATE category:image_to_image SET name="Image-to-Image", parent_categories=[category:computer_vision];
CREATE category:unconditional_image_generation SET name="Unconditional Image Generation", parent_categories=[category:computer_vision];
CREATE category:video_classification SET name="Video Classification", parent_categories=[category:computer_vision];
CREATE category:zero_shot_image_classification SET name="Zero-Shot Image Classification", parent_categories=[category:computer_vision];
CREATE category:mask_generation SET name="Mask Generation", parent_categories=[category:computer_vision];
CREATE category:zero_shot_object_detection SET name="Zero-Shot Object Detection", parent_categories=[category:computer_vision];

CREATE category:natural_language_processing SET name="Natural Language Processing";
-- subcategories for natural language processing
CREATE category:text_classification SET name="Text Classification", parent_categories=[category:natural_language_processing];
CREATE category:token_classification SET name="Token Classification", parent_categories=[category:natural_language_processing];
CREATE category:table_question_answering SET name="Table Question Answering", parent_categories=[category:natural_language_processing];
CREATE category:question_answering SET name="Question Answering", parent_categories=[category:natural_language_processing];
CREATE category:zero_shot_classification SET name="Zero-Shot Classification", parent_categories=[category:natural_language_processing];
CREATE category:translation SET name="Translation", parent_categories=[category:natural_language_processing];
CREATE category:summarization SET name="Summarization", parent_categories=[category:natural_language_processing];
CREATE category:conversational SET name="Conversational", parent_categories=[category:natural_language_processing];
CREATE category:text_generation SET name="Text Generation", parent_categories=[category:natural_language_processing];
CREATE category:text2text_generation SET name="Text2Text Generation", parent_categories=[category:natural_language_processing];
CREATE category:fill_mask SET name="Fill-Mask", parent_categories=[category:natural_language_processing];
CREATE category:sentence_similarity SET name="Sentence Similarity", parent_categories=[category:natural_language_processing];

CREATE category:audio SET name="Audio";
-- subcategories for Audio
CREATE category:text_to_speech SET name="Text-to-Speech", parent_categories=[category:audio];
CREATE category:text_to_audio SET name="Text-to-Audio", parent_categories=[category:audio];
CREATE category:automatic_speech_recognition SET name="Automatic Speech Recognition", parent_categories=[category:audio];
CREATE category:audio_to_audio SET name="Audio-to-Audio", parent_categories=[category:audio];
CREATE category:audio_classification SET name="Audio Classification", parent_categories=[category:audio];
CREATE category:voice_activity_detection SET name="Voice Activity Detection", parent_categories=[category:audio];
CREATE category:tabular SET name="Tabular", parent_categories=[category:audio];
CREATE category:tabular_classification SET name="Tabular Classification", parent_categories=[category:audio];
CREATE category:tabular_regression SET name="Tabular Regression", parent_categories=[category:audio];

CREATE category:simulation SET name="Simulation";
-- subcategories for Simulation
CREATE category:human_behavior SET name="Simulate Human Behavior", parent_categories=[category:simulation];
CREATE category:economic_behavior SET name="Simulate Economic Behavior", parent_categories=[category:simulation];
CREATE category:market_research SET name="Simulate Market Research", parent_categories=[category:simulation];
CREATE category:social_enagement SET name="Simulate Social Engagement", parent_categories=[category:simulation];
CREATE category:public_opinion SET name="Simulate Public Opinion", parent_categories=[category:simulation];
CREATE category:geopolitics SET name="Simulate Geopolitics", parent_categories=[category:simulation];

CREATE tag:math SET name="Math";
CREATE tag:education SET name="Education";
CREATE tag:language SET name="Language";
CREATE tag:general SET name="General";
CREATE tag:task_identification SET name="Task Identification";
CREATE tag:parallel_execution SET name="Parallel Execution";
CREATE tag:task_coordination SET name="Task Coordination";
CREATE tag:result_synthesis SET name="Result Synthesis";
CREATE tag:retrieval_augmented_generation SET name="Retrieval Augmented Generation";
CREATE tag:schema_based_tabular_data SET name="Schema-Based Tabular Data";

-- USERS
CREATE user:naptha SET 
    name="Naptha", 
    username="naptha1", 
    password=crypto::argon2::generate("great-password"),
    public_key="d3f40913bf024fbc0e7e17c298b5fa03c3518039bf71c170faf74c0694caad60503146befe78e62794c33bf7fe991175da838609c70d79d5e85bb9b1aa965a11"

;
--private_key="60a632f3e0875111199c4323a1b010bc4808e2a252b21ff366968cfc25af6444"

-- ORGANIZATIONS
CREATE organization:naptha SET name="Naptha", image="https://richardblythman.github.io/image-api/algovera/algovera-whiteBackground.png?w=200&amp;h=200&amp;f=face", owner=user:naptha1;
RELATE user:seller1->is_associated_with->organization:naptha;


-- AGENTS
CREATE agent:hello_world_agent SET name="hello_world_agent", description="A simple hello world agent", parameters="{firstname: str, surname: str}", author=user:naptha, module_url="https://github.com/NapthaAI/hello_world_agent", module_type="agent", execution_type="package", module_version="v0.16", module_entrypoint="run.py";
CREATE agent:simple_chat_agent SET name="simple_chat_agent", description="A simple chat agent", parameters="{tool_name: str, tool_input_data: str}", author=user:naptha, module_url="https://github.com/NapthaAI/simple_chat_agent", module_type="agent", execution_type="package", module_version="v0.16", module_entrypoint="run.py";
CREATE agent:babyagi_task_initiator SET name="babyagi_task_initiator", description="A simple agent for initiating tasks in BabyAGI", parameters="{objective: str}", author=user:naptha, module_url="https://github.com/NapthaAI/babyagi_task_initiator", module_type="agent", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
CREATE agent:babyagi_task_executor SET name="babyagi_task_executor", description="A simple agent for executing tasks in BabyAGI", parameters="{tool_name: str, tool_input_data: str}", author=user:naptha, module_url="https://github.com/NapthaAI/babyagi_task_executor", module_type="agent", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
CREATE agent:babyagi_task_finalizer SET name="babyagi_task_finalizer", description="A simple agent for finalizing tasks in BabyAGI", parameters="{task: str, objective: str}", author=user:naptha, module_url="https://github.com/NapthaAI/babyagi_task_finalizer", module_type="agent", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
CREATE agent:prediction_agent SET name="prediction_agent", description="A simple agent for making predictions about events", parameters="{prompt: str}", author=user:naptha, module_url="https://github.com/NapthaAI/prediction_agent", module_type="agent", execution_type="package", module_version="v0.3", module_entrypoint="run.py";
CREATE agent:debate_agent SET name="debate_agent", description="An agent for taking part in debate protocols", parameters="{agent_type: str, agent_name: str, conversation: List[ACLMessage]}", author=user:naptha, module_url="https://github.com/NapthaAI/debate_agent", module_type="agent", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
CREATE agent:napthaville_module SET name="napthaville_module", description="An agent for taking part in socail simulations", parameters="{task: str, task_params: Dict[str, Any]}", author=user:naptha, module_url="https://github.com/moarshy/napthaville_module", module_type="agent", execution_type="package", module_version="v0.36", module_entrypoint="run.py";
CREATE agent:random_number_agent SET name="random_number_agent", description="A simple agent for taking part in Keynesian beauty contests", parameters="{agent_name: str}", author=user:naptha, module_url="https://github.com/NapthaAI/random_number_agent", module_type="agent", execution_type="package", module_version="v0.6", module_entrypoint="run.py";
CREATE agent:tweets_to_character SET name="tweets_to_character", description="An agent for generating character personas from twitter data", parameters="{input_dir: str}", author=user:naptha, module_url="https://github.com/NapthaAI/tweets_to_character", module_type="agent", execution_type="package", module_version="v0.1", module_entrypoint="run.py";
CREATE agent:wikipedia_agent SET name="wikipedia_agent", description="An agent for querying wikipedia", parameters="{query: str}", author=user:naptha, module_url="https://github.com/NapthaAI/wikipedia_agent", module_type="agent", execution_type="package", module_version="v0.8", module_entrypoint="run.py";
CREATE agent:generate_image_agent SET name="generate_image_agent", description="An agent for generating images", parameters="{tool_name: str, tool_input_data: str}", author=user:naptha, module_url="https://github.com/NapthaAI/generate_image_agent", module_type="agent", execution_type="package", module_version="v0.4", module_entrypoint="run.py";

-- TOOLS
CREATE tool:generate_image_tool SET name="generate_image_tool", description="A simple tool for generating an image from text with Stable Diffusion", parameters="{tool_name: str, tool_input_data: str}", author=user:naptha, module_url="https://github.com/NapthaAI/generate_image_tool", module_type="tool", execution_type="package", module_version="v0.14", module_entrypoint="run.py";
CREATE tool:image_to_image SET name="image_to_image", description="A simple tool for generating an image from another image with Stable Diffusion", parameters="{prompt: str}", author=user:naptha, module_url="https://github.com/NapthaAI/image2image", module_type="tool", execution_type="package", module_version="v0.9", module_entrypoint="run.py";

-- ORCHESTRATORS
CREATE orchestrator:multiagent_chat SET name="multiagent_chat", description="Multi-agent network for chat", parameters="{prompt: str}", author=user:naptha, module_url="https://github.com/NapthaAI/multiagent_chat", module_type="orchestrator", execution_type="package", module_version="v0.17", module_entrypoint="run.py";
CREATE orchestrator:babyagi SET name="babyagi", description="Multi-agent network for running task-solving", parameters="{objective: str}", author=user:naptha, module_url="https://github.com/NapthaAI/babyagi", module_type="orchestrator", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
CREATE orchestrator:multiagent_debate SET name="multiagent_debate", description="A network of debating agents", parameters="{initial_claim: str, context: str, max_rounds: int}", author=user:naptha, module_url="https://github.com/NapthaAI/multiagent_debate", module_type="orchestrator", execution_type="package", module_version="v0.6", module_entrypoint="run.py";
CREATE orchestrator:keynesian_beauty_contest SET name="keynesian_beauty_contest", description="A network of agents that guess random numbers", parameters="{num_agents: int}", author=user:naptha, module_url="https://github.com/moarshy/keynesian_beauty_contest", module_type="orchestrator", execution_type="package", module_version="v0.3", module_entrypoint="run.py";
CREATE orchestrator:napthaville_chat SET name="napthaville_chat", description="Multi-agent network for chat between characters in Napthaville", parameters="{init_persona: str, target_persona: str}", author=user:naptha, module_url="https://github.com/moarshy/napthaville_chat", module_type="orchestrator", execution_type="package", module_version="v0.4", module_entrypoint="run.py";
CREATE orchestrator:napthaville_move SET name="napthaville_move", description="Multi-agent network for social simulations in Napthaville", parameters="{num_steps: int, sims_ipfs_hash: Optional[str]}", author=user:naptha, module_url="https://github.com/moarshy/napthaville_move", module_type="orchestrator", execution_type="package", module_version="v0.26", module_entrypoint="run.py";
CREATE orchestrator:multiagent_prediction SET name="multiagent_prediction", description="Multi-agent network for forecasting future events", parameters="{prompt: str}", author=user:naptha, module_url="https://github.com/NapthaAI/multiagent_prediction", module_type="orchestrator", execution_type="package", module_version="v0.2", module_entrypoint="run.py";

-- ENVIRONMENTS
CREATE environment:groupchat_environment SET name="groupchat_environment", description="Environment mechanism for group chat between agents.", parameters="{function_name: str, function_input_data: Optional[Dict[str, Any]]}", author=user:naptha, module_url="https://github.com/NapthaAI/groupchat_environment", module_type="environment", execution_type="package", module_version="v0.2", module_entrypoint="run.py";

-- PERSONAS
CREATE persona:richard_twitter SET name="richard_twitter", description="Persona for Richard generated from twitter exports", parameters="{name: str, bio: List[str], lore: List[str], adjectives: List[str], topics: List[str], style: Dict[str, List[str]], messageExamples: List, postExamples: List}", author=user:naptha, module_url="https://huggingface.co/datasets/NapthaAI/twitter_personas", module_type="persona", module_version="v0.1", module_entrypoint="richard.json";
CREATE persona:interstellarninja_twitter SET name="interstellarninja_twitter", description="Persona for Interstellar Ninja generated from twitter exports", parameters="{name: str, bio: List[str], lore: List[str], adjectives: List[str], topics: List[str], style: Dict[str, List[str]], messageExamples: List, postExamples: List}", author=user:naptha, module_url="https://huggingface.co/datasets/NapthaAI/twitter_personas", module_type="persona", module_version="v0.1", module_entrypoint="interstellarninja.json";
CREATE persona:marketagents_aileenmay SET name="marketagents_aileenmay", description="Market agent persona for Aileen May", parameters="{name: str, role: str, persona: str, objectives: List[str], trader_type: List[str]}", author=user:naptha, module_url="https://huggingface.co/datasets/NapthaAI/market_agents_personas", module_type="persona", module_version="v0.1", module_entrypoint="market_agents_personas/data/Aileen_May.yaml";
CREATE persona:one_million_personas_0000013 SET name="one_million_personas_0000013", description="Personas generated from the paper Scaling Synthetic Data Creation with 1M Personas", parameters="{persona: str}", author=user:naptha, module_url="https://huggingface.co/datasets/proj-persona/PersonaHub", module_type="persona", module_version="v0.1", module_entrypoint="persona.jsonl:0000013";

-- KNOWLEDGE BASES
CREATE kb:wikipedia_kb SET name="wikipedia_kb", description="Knowledge base for Wikipedia content", parameters='{"function_name": "str", "function_input_data": "Optional[Dict[str, Any]]"}', author=user:naptha, module_url="https://github.com/NapthaAI/wikipedia_kb", module_type="kb", execution_type="package", module_version="v0.6", module_entrypoint="run.py";
CREATE kb:embedding_kb SET name="embedding_kb", description="Knowledge base for testing embedding", parameters='{"function_name": "str", "function_input_data": "Optional[Dict[str, Any]]"}', author=user:naptha, module_url="https://github.com/NapthaAI/embedding_kb", module_type="kb", execution_type="package", module_version="v0.4", module_entrypoint="run.py";
CREATE kb:groupchat_kb SET name="groupchat_kb", description="Knowledge base for groupchat", parameters='{"func_name": "str", "func_input_data": "Optional[Dict[str, Any]]"}', author=user:naptha, module_url="https://github.com/NapthaAI/groupchat_kb", module_type="kb", execution_type="package", module_version="v0.1", module_entrypoint="run.py";

-- MEMORIES
CREATE memory:cognitive_memory SET name="cognitive_memory", description="Cognitive memory", parameters='{"func_name": "str", "func_input_data": "Optional[Dict[str, Any]]"}', author=user:naptha, module_url="https://github.com/NapthaAI/cognitive_memory", module_type="memory", execution_type="package", module_version="v0.2", module_entrypoint="run.py";
