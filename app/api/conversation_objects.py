#!/usr/bin/env python3

from collections import OrderedDict

class Conversation:
    turn_mapper = OrderedDict() 


    def __init__(self,project_id, project_name,export_time, doccano_conv_id, conv_filename):
        self.project_id = project_id
        self.project_name = project_name
        self.export_time = export_time
        self.doccano_conv_id = doccano_conv_id
        self.filename = conv_filename
       
    '''
    project_id,project_name, export_time, doccano_conv_id, conv_filename
    def __init__(self,project_id, doccano_conv_id, conv_filename):
        self.project_id = project_id
        self.doccano_conv_id = doccano_conv_id
        self.filename = conv_filename
    '''


class Turn:
    def __init__(self, turn_id, speaker, start, stop, sentences, turn_text, turn_length):
        self.id = turn_id 
        self.speaker = speaker
        self.start = start
        self.end = stop
        self.sentences = sentences
        self.text = turn_text
        self.lenght = turn_length

class Annotation:
        id = int()
        start = int()
        end = int()
        user = ""
        entire_annotation = ""
        sent_anno_intersection = ""
        
        def __init__(self,annotation_id, start, end, label, user, entire_annotation, sent_anno_intersection):
            self.id = annotation_id
            self.start = start
            self.end = end
            self.user = user
            self.entire_annotation = entire_annotation
            self.sent_anno_intersection = sent_anno_intersection
            self.label = label

class Sentence:
    has_annotation = False
    tagged_text = ""
    def __init__(self,turn_id, turn_sent_id, conv_sent_id, sentence_start, sentence_end, sentence_text, sentence_length):
        self.turn_id = turn_id
        self.turn_sent_id = turn_sent_id 
        self.conv_sent_id = conv_sent_id
        self.text = sentence_text
        self.start = sentence_start
        self.end = sentence_end
        self.length =  sentence_length
        self.annotations = []