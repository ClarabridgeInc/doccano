#!/usr/bin/env python3
import csv
import json
from collections import OrderedDict
import difflib
from copy import deepcopy
from . import conversation_objects

import nltk
nltk.download('punkt')
from nltk.tokenize import sent_tokenize



def conversation_parser(transcript_text):
    conv_length = len(transcript_text)
    turns = transcript_text.split("\n") 
    conv_sent_id = 0
    turn_id = 0
    turn_start = 0
    turn_mapper = OrderedDict()  # map span of turn (tuple) to turn index

    #Analysing at turn level
    for t in turns:
        turn_sentences = []
        next_turn = turn_start + len(t) + 1
        turn_sent_id = 0
        t = t.strip()
        
        if t.startswith("AGENT:"):
            speaker = 'AGENT'
            #t = t.replace('AGENT:','') 
        elif t.startswith("CLIENT:"):
            speaker = "CLIENT"
            #t = t.replace('CLIENT:','')
        else:
            speaker = "UNKNOWN"
        
        turn_id += 1
        turn_start = transcript_text.find(t, turn_start, next_turn)
        turn_end = transcript_text.find(t, turn_start,next_turn)+len(t)+1
        turn_text = t 
        turn_length = len(t)
        
        if t.startswith("AGENT:"):
            t = t.replace('AGENT: ','') 

        elif t.startswith("CLIENT:"):
            t = t.replace('CLIENT: ','')

        sentences = sent_tokenize(t)
    
        #Analysing at sentence level
        for sent in sentences:
            sentence_start = transcript_text.find(sent, turn_start, next_turn)
            sentence_end = transcript_text.find(sent,turn_start,next_turn)+len(sent) # for a dot and a space
            sentence_length = len(sent)
            sentence_text = sent
            turn_sent_id += 1
            conv_sent_id += 1

            sentence = conversation_objects.Sentence(turn_id, turn_sent_id ,conv_sent_id, sentence_start, sentence_end, sentence_text, sentence_length)
            turn_sentences.append(sentence)
       
        turn = conversation_objects.Turn(turn_id, speaker, turn_start, turn_end, turn_sentences, turn_text, turn_length)
        turn_mapper[(int(turn_start), int(turn_end))] = turn
        turn_start = next_turn
    
    return turn_mapper


def turns_in_annotation(turn_keys,annotation,conversation):
    lower_limit = False
    upper_limit = False
    turns_involved = set()
    for key_index in range(0, len(turn_keys)):
        if(turn_keys[key_index][0]> annotation.start and lower_limit == False):
            lower_turn_key = turn_keys[key_index - 1]
            turns_involved.add(turn_keys[key_index-1])
            lower_limit = True

        if(turn_keys[key_index][1] >= annotation.end and upper_limit == False):
            upper_turn_key = turn_keys[key_index]
            turns_involved.add(turn_keys[key_index])
            upper_limit = True

        if(lower_limit == True and upper_limit == False):
            turns_involved.add(turn_keys[key_index])

        if(upper_limit == True and lower_limit == True):
            break
    return turns_involved


def  link_annotation_to_sentence(annotation,conversation,turns_involved,transcript):
    for turn_involved in turns_involved:
        for sentence_involved in conversation.turn_mapper[turn_involved].sentences:

            if(sentence_involved.start >= annotation.end):
                continue
            if(sentence_involved.end < annotation.start):
                continue
            if (annotation.start == sentence_involved.end):
                continue
            if (annotation.end == sentence_involved.start):
                continue
            else:
                matching_text_sequences =difflib.SequenceMatcher(None, sentence_involved.text,transcript['text'][int(annotation.start):int(annotation.end)])
                sub_start = matching_text_sequences.get_matching_blocks()[0].a
                sub_len = matching_text_sequences.get_matching_blocks()[0].size
                sub_end = sub_start + sub_len 
                annotation_copy = deepcopy(annotation)
                annotation_copy.sent_anno_intersection = sentence_involved.text[sub_start:sub_end]
                sentence_involved.annotations.append(annotation_copy)
                if(sentence_involved.has_annotation == True):
                    pass
                else:
                    sentence_involved.has_annotation = True

    return conversation

def match_annotations_to_sentences(conversation, conv_annotations,transcript,label_dict, annotation_count): 
    turn_keys = [k for k in conversation.turn_mapper.keys()]    
    for anno in conv_annotations:
        annotation_count += 1
        entire_annotation = transcript['text'][int( anno["start_offset"]):int(anno["end_offset"])]
        annotation = conversation_objects.Annotation(annotation_count, int( anno["start_offset"]), int(anno["end_offset"]),label_dict[anno["label"]], str(anno["user"]), entire_annotation, "")
        turns_involved =  turns_in_annotation(turn_keys,annotation,conversation)
        conversation = link_annotation_to_sentence(annotation,conversation,turns_involved,transcript)
    return conversation, annotation_count

def write_datafile(conversations):
    #filename = "export.tsv"
    filename = f"project_{conversations[0].project_id}_name_{conversations[0].project_name}_time_{conversations[0].export_time}.tsv"
    with open("/mounted/exported/" + filename, "w") as output_file:
        tsv_writer = csv.writer(output_file, delimiter='\t')
        tsv_writer.writerow(['project_id','project_name','export_time','doccano_conv_id','conv_filename', 'speaker', 'turn_id', 'turn_text', 'turn_sentence_id','conv_sent_id','sentence_text', 'entire_annotation','phrase_annotated','label','annotation_id','user'])
        #tsv_writer.writerow(['project_id','project_name','export_time','doccano_conv_id','conv_filename', 'speaker', 'turn_id','turn_start', 'turn_end', 'turn_text', 'turn_sentence_id','conv_sent_id','sentence_text','sentence_start','sentence_end', 'entire_annotation','phrase_annotated','label','annotation_id','tag_start','tag_end','user'])
        for conversation in conversations:
            for turn in conversation.turn_mapper.items():
                for sentence in turn[1].sentences: 
                    if(sentence.has_annotation == True):
                        for annotation in sentence.annotations:
                            tsv_writer.writerow([conversation.project_id, conversation.project_name, conversation.export_time, conversation.doccano_conv_id,conversation.filename,turn[1].speaker,turn[1].id,turn[1].text,sentence.turn_sent_id,sentence.conv_sent_id, sentence.text, annotation.entire_annotation,annotation.sent_anno_intersection ,annotation.label,annotation.id,annotation.user])
                            #tsv_writer.writerow([conversation.project_id, conversation.project_name, conversation.export_time, conversation.doccano_conv_id,conversation.filename,turn[1].speaker,turn[1].id,turn[1].start,turn[1].end,turn[1].text,sentence.turn_sent_id,sentence.conv_sent_id, sentence.text, sentence.start, sentence.end,annotation.entire_annotation,annotation.sent_anno_intersection ,annotation.label,annotation.id, annotation.start, annotation.end,annotation.user])
                    else:
                        tsv_writer.writerow([conversation.project_id, conversation.project_name, conversation.export_time, conversation.doccano_conv_id,conversation.filename,turn[1].speaker,turn[1].id,turn[1].text,sentence.turn_sent_id,sentence.conv_sent_id, sentence.text])
                        #tsv_writer.writerow([conversation.project_id,conversation.project_name, conversation.export_time, conversation.doccano_conv_id,conversation.filename,turn[1].speaker,turn[1].id,turn[1].start,turn[1].end, turn[1].text, sentence.turn_sent_id, sentence.conv_sent_id, sentence.text, sentence.start, sentence.end])
                    
                       

def export_post_process(label_dict, transcripts,  project_name, project_id, export_time):
    annotation_count = 0
    conversations = [] # A list containing all the Conversation objects. An object per conversation.

    #Split throught every doc
    for transcript in transcripts:
        doccano_conv_id = transcript['id']
        try:
            conv_filename = transcript['meta']['filename']
        except:
            conv_filename= "NO_FILENAME_FOUND"

        conversation = conversation_objects.Conversation(project_id,project_name, export_time, doccano_conv_id, conv_filename)
        conversation.turn_mapper = conversation_parser(transcript['text'])
        #Dealing with annotations
        conversation,annotation_count = match_annotations_to_sentences(conversation, transcript['annotations'], transcript,label_dict,annotation_count)
        conversations.append(conversation)

        write_datafile(conversations)
    

    
   






