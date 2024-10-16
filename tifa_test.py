from tifascore import get_question_and_answers, filter_question_and_answers, UnifiedQAModel, tifa_score_benchmark, tifa_score_single,  VQAModel
from tifascore import get_llama2_pipeline, get_llama2_question_and_answers
import json
#import openai


if __name__ == "__main__":
    
    #####################################
    ## Test TIFA score on benchmark
    #####################################
    
    # test tifa benchmarking
    """ results = tifa_score_benchmark("mplug-large", "sample/sample_question_answers.json", "sample/sample_imgs.json")
    with open("sample/sample_evaluation_result.json", "w") as f:
        json.dump(results, f, indent=4) """
    
    
    #####################################
    ## Test TIFA score on one image
    #####################################
    
    # prepare the models
    #openai.api_key = "[OpenAI key]"
    unifiedqa_model = UnifiedQAModel("allenai/unifiedqa-v2-t5-large-1363200")
    vqa_model = VQAModel("mplug-large")
    
    
    img_path = "sample/drawbench_8.jpg"
    text = "two yellow bananas."
    
    # Generate questions with GPT-3.5-turbo
    #gpt3_questions = get_question_and_answers(text)
    #print("-----------------------Questions------------------\n",gpt3_questions)

    # Generate questions with llama_2
    pipeline = get_llama2_pipeline("tifa-benchmark/llama2_tifa_question_generation")
    llama2_questions = get_llama2_question_and_answers(pipeline, "two yellow bananas.")
    
    # Filter questions with UnifiedQA
    #filtered_questions = filter_question_and_answers(unifiedqa_model, gpt3_questions)
    
    # Filter questions with UnifiedQA
    filtered_questions = filter_question_and_answers(unifiedqa_model, llama2_questions)

    # See the questions
    print(filtered_questions)

    # calucluate TIFA score
    result = tifa_score_single(vqa_model, filtered_questions, img_path)
    print(f"TIFA score is {result['tifa_score']}")
    #print(result)
    
    
    
