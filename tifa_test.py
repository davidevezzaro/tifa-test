from tifascore import get_question_and_answers, filter_question_and_answers, UnifiedQAModel, tifa_score_benchmark, tifa_score_single,  VQAModel
from tifascore import get_llama2_pipeline, get_llama2_question_and_answers
import json
from config import RunConfig,TifaVersion
from transformers import pipeline
import os
import pandas as pd
from PIL import Image,ImageDraw, ImageFont
import numpy as np
import csv
import torch
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
import torchvision.utils
import torchvision.transforms.functional as tf
import math

def readCSV(eval_path):
    df = pd.read_csv(os.path.join(eval_path,'QBench.csv'),dtype={'id': str})
    return df

def assignResults(id, prompt,seed,result):
    row_reference={
                'id':None,
                'prompt':None,
                'seed':None, 
                'tifa_score':None,
                'object_s':0,
                'human_s':0,
                'animal_s':0,
                'animal/human_s':0,
                'food_s':0,
                'activity_s':0,
                'attribute_s':0,
                'counting_s':0,
                'color_s':0,
                'material_s':0,
                'spatial_s':0,
                'location_s':0,
                'shape_s':0,
                'other_s':0,
            }
    new_row = row_reference.copy()

    new_row['id']=id
    new_row['prompt']=prompt
    new_row['seed']=seed
    
    count_questions_by_type={
        'object_s':0,
        'human_s':0,
        'animal_s':0,
        'animal/human_s':0,
        'food_s':0,
        'activity_s':0,
        'attribute_s':0,
        'counting_s':0,
        'color_s':0,
        'material_s':0,
        'spatial_s':0,
        'location_s':0,
        'shape_s':0,
        'other_s':0
    }

    #count number of questions by type
    for question in result["question_details"].keys(): 
        type = result["question_details"][question]["element_type"]+'_s'
        count_questions_by_type[type]=count_questions_by_type[type]+1

    #accumulate scores
    for question in result["question_details"].keys():    
        score_by_type=result["question_details"][question]["scores"]
        type = result["question_details"][question]["element_type"]+'_s'
        new_row[type]=new_row[type]+score_by_type

    #average accuracies
    for scores in new_row.keys():
        if scores not in ["id", "prompt", "seed", "tifa_score"]:
            number_of_questions = count_questions_by_type[scores]
            if(number_of_questions != 0):
                new_row[scores]=new_row[scores]/number_of_questions

    new_row['tifa_score'] = result['tifa_score']
    return new_row

def assignQuestionDetails(id, prompt,seed,scores):
    questions={
        "question":{}
    }

    for question in scores["question_details"].keys():
        questions['question'][question]={
                'element':scores["question_details"][question]["element"],
                'element_type':scores["question_details"][question]["element_type"],
                'choices':scores["question_details"][question]["choices"],
                'free_form_vqa':scores["question_details"][question]["free_form_vqa"],
                'multiple_choice_vqa':scores["question_details"][question]["multiple_choice_vqa"],
                'score_by_question':scores["question_details"][question]["scores"]
            } 
    return questions

def bbIoU(boxA, boxB):
	# determine the (x, y)-coordinates of the intersection rectangle
	xA = max(boxA[0], boxB[0])
	yA = max(boxA[1], boxB[1])
	xB = min(boxA[2], boxB[2])
	yB = min(boxA[3], boxB[3])
	# compute the area of intersection rectangle
	interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)
	# compute the area of both the prediction and ground-truth
	# rectangles
	boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
	boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)
	# compute the intersection over union by taking the intersection
	# area and dividing it by the sum of prediction + ground-truth
	# areas - the interesection area
	iou = interArea / float(boxAArea + boxBArea - interArea)
	# return the intersection over union value
	return iou

def calculate_tifa(config : RunConfig):
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
        
        for model in models_to_evaluate:
            scores_df = pd.DataFrame({
            'id':[],
            'prompt':[],
            'seed':[], 
            'tifa_score':[],
            'object_s':[],
            'human_s':[],
            'animal_s':[],
            'animal/human_s':[],
            'food_s':[],
            'activity_s':[],
            'attribute_s':[],
            'counting_s':[],
            'color_s':[],
            'material_s':[],
            'spatial_s':[],
            'location_s':[],
            'shape_s':[],
            'other_s':[]
            })

            question_details={
                'id_prompt_seed':{}
            }

                
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
            
            #initialization
            prompt = images[0]['prompt']
            llama2_questions=get_llama2_question_and_answers(pipeline,prompt)
            filtered_questions=filter_question_and_answers(unifiedqa_model, llama2_questions)

            for image in images:
                img_path = image['img_path']
                if(prompt != image['prompt']):#when prompt changes, questions and answers change too otherwise it's unnecessary
                    prompt = image['prompt']
                    llama2_questions = get_llama2_question_and_answers(pipeline,prompt)
                    # Filter questions with UnifiedQA
                    filtered_questions = filter_question_and_answers(unifiedqa_model, llama2_questions)

                print("----")
                print("PROMPT:",prompt)
                print("PATH:",img_path)
                
                # calculate TIFA score
                scores = tifa_score_single(vqa_model, filtered_questions, img_path)

                new_scores_row=assignResults(image['prompt_id'],image['prompt'],image['seed'],scores)
                new_question_details_rows=assignQuestionDetails(image['prompt_id'],image['prompt'],image['seed'],scores)

                scores_df = pd.concat([scores_df, pd.DataFrame([new_scores_row])], ignore_index=True)
                question_details['id_prompt_seed'][image['prompt_id']+image['prompt'].replace(" ", "")+str(image['seed'])]=new_question_details_rows

                print("SCORE: ", scores['tifa_score'])

            
            #output to csv
            scores_df.to_csv(os.path.join(model['batch_gen_images_path'],model['folder_name']+'.csv'), index=False)
            #dump question details to json
            with open(os.path.join(model['batch_gen_images_path'],model['folder_name']+'.json'), 'w') as fp:
                json.dump(question_details, fp)

def calculate_extended_tifa(config : RunConfig):
    #Load the models
    unifiedqa_model = UnifiedQAModel(config.qa_model)
    vqa_model = VQAModel(config.vqa_model)
    #llama2 for local gpt model, from Hugging Face
    tifa_pipeline = get_llama2_pipeline(config.gpt_model)
    #Zero shot object detection pipeline
    object_detector = pipeline("zero-shot-object-detection", model="google/owlvit-base-patch32", device="cuda")

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
        
        for model in models_to_evaluate:
            scores_df = pd.DataFrame({
            'id':[],
            'prompt':[],
            'seed':[], 
            'tifa_score':[],
            'object_s':[],
            'human_s':[],
            'animal_s':[],
            'animal/human_s':[],
            'food_s':[],
            'activity_s':[],
            'attribute_s':[],
            'counting_s':[],
            'color_s':[],
            'material_s':[],
            'spatial_s':[],
            'location_s':[],
            'shape_s':[],
            'other_s':[]
            })

            question_details={
                'id_prompt_seed':{}
            }

            images = [] # attributes for each generated image
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
                                'seed':img_filename.split('.')[0],
                                'obj1': row['obj1'] if row['obj1']is not None else math.nan,
                                'bbox1':row['bbox1']if row['bbox1']is not None else math.nan,
                                'obj2': row['obj2'] if row['obj2']is not None else math.nan,
                                'bbox2':row['bbox2']if row['bbox2']is not None else math.nan,
                                'obj3': row['obj3'] if row['obj3']is not None else math.nan,
                                'bbox3':row['bbox3']if row['bbox3']is not None else math.nan,
                                'obj4': row['obj4'] if row['obj4']is not None else math.nan,
                                'bbox4':row['bbox4']if row['bbox4']is not None else math.nan,
                            })
                            
            images.sort(key=lambda x: (int(x['prompt_id']), int(x['seed'])))
            print("Starting evaluation process")
            
            #initialization
            prompt = images[0]['prompt']
            ground_truth = {} #ground truth bounding boxes
            
            if not (isinstance(images[0]['obj1'], (int,float)) and math.isnan(images[0]['obj1'])):
                ground_truth[images[0]['obj1']] = [int(x) for x in images[0]['bbox1'].split(',')]
            if not (isinstance(images[0]['obj2'], (int,float)) and math.isnan(images[0]['obj2'])):
                ground_truth[images[0]['obj2']] = [int(x) for x in images[0]['bbox2'].split(',')]
            if not (isinstance(images[0]['obj3'], (int,float)) and math.isnan(images[0]['obj3'])):
                ground_truth[images[0]['obj3']] = [int(x) for x in images[0]['bbox3'].split(',')]
            if not (isinstance(images[0]['obj4'], (int,float)) and math.isnan(images[0]['obj4'])):
                ground_truth[images[0]['obj4']] = [int(x) for x in images[0]['bbox4'].split(',')]
            
            llama2_questions=get_llama2_question_and_answers(tifa_pipeline,prompt)
            filtered_questions=filter_question_and_answers(unifiedqa_model, llama2_questions)

            for image in images:
                img_path = image['img_path']
                    
                if(prompt != image['prompt']):#when prompt changes, questions and answers change too otherwise it's unnecessary
                    prompt = image['prompt']
                    ground_truth.clear()
                    
                    if not (isinstance(image['obj1'], (int,float)) and math.isnan(image['obj1'])):
                        ground_truth[image['obj1']]= [int(x) for x in image['bbox1'].split(',')]
                    if not (isinstance(image['obj2'], (int,float))and math.isnan(image['obj2'])):
                        ground_truth[image['obj2']]= [int(x) for x in image['bbox2'].split(',')]
                    if not (isinstance(image['obj3'], (int,float)) and math.isnan(image['obj3'])):
                        ground_truth[image['obj3']]= [int(x) for x in image['bbox3'].split(',')]
                    if not (isinstance(image['obj4'], (int,float)) and math.isnan(image['obj4'])):
                        ground_truth[image['obj4']]= [int(x) for x in image['bbox4'].split(',')]              
                    
                    llama2_questions = get_llama2_question_and_answers(tifa_pipeline,prompt)
                    # Filter questions with UnifiedQA
                    filtered_questions = filter_question_and_answers(unifiedqa_model, llama2_questions)
                
                print("----")
                print("PROMPT:",prompt)
                print("PATH:",img_path)
                
                # calculate TIFA score
                scores = tifa_score_single(vqa_model, filtered_questions, img_path)

                new_scores_row=assignResults(image['prompt_id'],image['prompt'],image['seed'],scores)
                new_question_details_rows=assignQuestionDetails(image['prompt_id'],image['prompt'],image['seed'],scores)

                scores_df = pd.concat([scores_df, pd.DataFrame([new_scores_row])], ignore_index=True)
                question_details['id_prompt_seed'][image['prompt_id']+image['prompt'].replace(" ", "")+str(image['seed'])]=new_question_details_rows
                print("SCORE: ", scores['tifa_score'])
                
                # Updated pipeline for object detection
                pil_image = Image.open(img_path).convert("RGB")
                preds = object_detector(pil_image, candidate_labels=ground_truth.keys())
                 
                predictions={}
                for p in preds:
                    predictions[p['label']]=list(p['box'].values())          
                
                """ #calculate IoU
                    if (len(predictions)!=0):
                        for label in list(predictions.keys()):
                            print("IoU over: "+label+" - "+ str(round(bbIoU(predictions[label],ground_truth[label]),2))) 
                """   
                #draw the bounding predicted bounding boxes
                if(len(predictions)!=0):
                    edited_image=torchvision.utils.draw_bounding_boxes(tf.pil_to_tensor(Image.open(img_path[:-4]+"_bboxes.png").convert("RGB")),
                                                            torch.Tensor(list(predictions.values())),
                                                            colors=['yellow', 'yellow', 'yellow', 'yellow', 'yellow', 'yellow', 'yellow', 'yellow'],
                                                            width=5,
                                                            font='font.ttf',
                                                            font_size=20)
                    #to draw on the image
                    edited_image = tf.to_pil_image(edited_image)
                    
                    draw = ImageDraw.Draw(edited_image)
                    
                    text = "IoU\n"
                    font_path = "font.ttf"  # Update this path if needed
                    font_size = 25
                    font = ImageFont.truetype(font_path, font_size)
                    
                    #calculate IoU
                    if (len(predictions)!=0):
                        for label in list(predictions.keys()):
                            print("IoU over: "+label+" - "+ str(round(bbIoU(predictions[label],ground_truth[label]),2)))
                            text = text+label+" : "+ str(round(bbIoU(predictions[label],ground_truth[label]),2))+"\n" 
                            
                    text = text[:-1]
                    text_width, text_height = draw.textsize(text, font=font)
                    padding = 10
                    text_x = 512 - text_width - 10  # 10 pixels padding from the right edge
                    text_y = 10  # 10 pixels padding from the top edge
                    
                    background_x0 = text_x - padding  # left
                    background_y0 = text_y - padding  # top
                    background_x1 = text_x + text_width + padding  # right
                    background_y1 = text_y + text_height + padding  # bottom
                    draw.rectangle([background_x0, background_y0, background_x1, background_y1], fill="white")

                    
                    draw.text((text_x, text_y), text, font=font, fill="black")
                    edited_image.save(os.path.join(image['prompt_gen_images_path'],image['img_filename'][:-4]+'_detection.png'))
                    
                    
                    #tf.to_pil_image(edited_image).save(os.path.join(image['prompt_gen_images_path'],image['img_filename'][:-4]+'_detection.png'))
                else:
                    print("Warning: no objects found by the object detector!")

            #output to csv
            scores_df.to_csv(os.path.join(model['batch_gen_images_path'],model['folder_name']+'.csv'), index=False)
            #dump question details to json
            with open(os.path.join(model['batch_gen_images_path'],model['folder_name']+'.json'), 'w') as fp:
                json.dump(question_details, fp)

def main(config:RunConfig):
    if(config.tifa_version==TifaVersion.REGULAR):
        calculate_tifa(config)
    elif(config.tifa_version==TifaVersion.EXTENDED):
        calculate_extended_tifa(config)
    
    #test_obj_dect()

def test_obj_dect():
    #Zero shot object detection pipeline
    detector = pipeline("zero-shot-object-detection", model="google/owlvit-base-patch32", device="cuda")

    image_path = "evaluation/QBench/QBench-CAG/003_A bus next to a bench with a bird and a pizza/14.jpg"

    # Open the image from the specified path
    image = Image.open(image_path).convert("RGB")

    predictions = detector(image, candidate_labels=["bus","bench","bird","pizza"])
    
    predicted_labels=[]
    predicted_bboxes=[]
    for prediction in predictions:
        predicted_labels.append(prediction['label'])
        temp_coordinates=[]
        for value in prediction['box'].values():
            temp_coordinates.append(value)
        predicted_bboxes.append(temp_coordinates)

    #draw the bounding boxes
    image=torchvision.utils.draw_bounding_boxes(tf.pil_to_tensor(image),
                                                torch.Tensor(predicted_bboxes),
                                                labels=["bus","bench","bird","pizza"],
                                                colors=['yellow', 'yellow', 'yellow', 'yellow', 'yellow', 'black', 'gray', 'white'],
                                                width=4,
                                                font="font.ttf",
                                                font_size=25)

    image=torchvision.utils.draw_bounding_boxes(image,
                                                torch.Tensor([[2,121,251,460],[274,345,503,496],[344,32,500,187],[58,327,187,403]]),
    
                                                colors=['red', 'purple', 'orange', 'green', 'yellow', 'black', 'gray', 'white'],
                                                width=4,
                                                font="font.ttf",
                                                font_size=25)
    
    tf.to_pil_image(image).save("pizza_bboxes.png")
    print("gt_bboxes",[2,121,251,460])
    print("predicted_bboxes",predicted_bboxes[0])
    print("IoU bus:",bbIoU(predicted_bboxes[0],[2,121,251,460]))
    
    print("gt_bboxes",[274,345,503,496])
    print("predicted_bboxes",predicted_bboxes[1])
    print("IoU bench:",bbIoU(predicted_bboxes[1],[274,345,503,496]))

    print("gt_bboxes",[344,32,500,187])
    print("predicted_bboxes",predicted_bboxes[2])
    print("IoU bird:",bbIoU(predicted_bboxes[2],[344,32,500,187]))
    
    print("gt_bboxes",[58,327,187,303])
    print("predicted_bboxes",predicted_bboxes[3])
    print("IoU pizza:",bbIoU(predicted_bboxes[3],[58,327,187,303]))
    

    """ model_id = "IDEA-Research/grounding-dino-base"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)

    image_path = "evaluation/QBench/QBench-CAG/001_A bus and a bench/4.jpg"

    # Open the image from the specified path
    image = Image.open(image_path).convert("RGB")
    # Check for cats and remote controls
    # VERY important: text queries need to be lowercased + end with a dot
    text = "a computer. a bench."

    inputs = processor(images=image, text=text, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    results = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        box_threshold=0.4,
        text_threshold=0.3,
        target_sizes=[image.size[::-1]]
    )
    print(results) """

if __name__ == "__main__":
    main(RunConfig())
    
    
