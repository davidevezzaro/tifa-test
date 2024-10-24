from tifascore import get_question_and_answers, filter_question_and_answers, UnifiedQAModel, tifa_score_benchmark, tifa_score_single,  VQAModel
from tifascore import get_llama2_pipeline, get_llama2_question_and_answers
import json
from config import RunConfig
import os
import pandas as pd
import csv

def readCSV(eval_path):
    df = pd.read_csv(os.path.join(eval_path,'QBench.csv'),dtype={'id': str})
    return df

def main(config : RunConfig):
    #Load the models
    unifiedqa_model = UnifiedQAModel(config.qa_model)
    vqa_model = VQAModel(config.vqa_model)
    #llama2 for local gpt model, from Hugging Face
    pipeline = get_llama2_pipeline(config.gpt_model)

    if not (os.path.isdir(config.eval_path)):
        print("Evaluation folder not found!")
    else:
        
        models_to_evaluate = []

        for model in os.listdir(config.eval_path):
            if(os.path.isdir((os.path.join(config.eval_path,model)))):
                #key is the model name
                models_to_evaluate.append({
                    'batch_gen_images_path':(os.path.join(config.eval_path,model)),#example:evaluation/QBench/QBench-SD14
                    'folder_name':model, #example:QBench-SD14,
                    'name':model[model.find('-')+1:]
                    })
        
        headers = ['id', 'prompt', 'seed', 'object', 'object', 'human', 'human', 'animal', 'animal', 'food', 'food', 'activity', 'activity', 'attribute', 'attribute', 'counting', 'counting', 'color', 'color', 'material', 'material', 'spatial', 'spatial', 'location', 'location', 'shape', 'shape', 'other', 'other', 'tifa']
        
        for model in models_to_evaluate:
            images = []
            #id,prompt,obj1,bbox1,token1,obj2,token2,obj3,token3,obj4,bbox4,token4
            prompt_collection = readCSV(config.eval_path)
            for index,row in prompt_collection.iterrows(): 
                #prompt_img_path = os.path.join(model[0],prompt[0]+'_'+prompt[1])
                prompt_gen_images_path = os.path.join(model['batch_gen_images_path'],row['id']+'_'+row['prompt'])
                #prompt = prompt[1]
                for img_filename in os.listdir(prompt_gen_images_path):
                    if not img_filename.endswith((".csv",".png")):
                        img_path = os.path.join(prompt_gen_images_path,img_filename)
                        if(os.path.isfile(img_path)):
                            images.append({
                                'prompt_gen_images_path':prompt_gen_images_path,
                                'img_path': img_path,
                                'img_filename':img_filename,
                                'prompt_id':row['id'],
                                'prompt':row['prompt'],
                                'model':model['name'],
                                'seed':img_filename.split('.')[0]
                            })
                            
            images.sort(key=lambda x: (int(x['prompt_id']), int(x['seed'])))
            
            print("Starting evaluation process")
            
            #write mode
            with open(prompt_collection[0]['model']+'.csv', mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(headers)

            #append mode
            with open(prompt_collection[0]['model']+'.csv', mode='a', newline='') as file:
                writer = csv.writer(file)

                #headers = {'id', 'prompt', 'seed', 'object', 'object', 'human', 'score', 'animal', 'animal', 'food', 'food', 'activity', 'activity', 'attribute', 'attribute', 'counting', 'counting', 'color', 'color', 'material', 'material', 'spatial', 'spatial', 'location', 'location', 'shape', 'shape', 'other', 'tifa_score'}
        
                
                for image in images:

                    prompt = image['prompt']
                    img_path = image['img_path']

                    print("----")
                    print("PROMPT:",prompt)
                    print("PATH:",img_path)

                    llama2_questions = get_llama2_question_and_answers(pipeline,prompt)
                
                    # Filter questions with UnifiedQA
                    filtered_questions = filter_question_and_answers(unifiedqa_model, llama2_questions)

                    # calculate TIFA score
                    result = tifa_score_single(vqa_model, filtered_questions, img_path)
                    print("tifa score: ",result['tifa_score'])
                    print("Questions:")
                    for question in result["question_details"].keys():
                        print(question," | Category: ",result["question_details"][question]["element_type"], " | Score: ",result["question_details"][question]["scores"])
"""                         row = [row_data.get(header, None) for header in headers]
                        writer.writerow(row)  # Write the specified row """

if __name__ == "__main__":

    main(RunConfig())
    
    
