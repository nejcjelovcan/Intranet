from django.shortcuts import render_to_response, get_object_or_404
from django.db.models.query import Q
from django.template.defaultfilters import slugify
from django import forms
from django.template import RequestContext, Context
from django.template.defaultfilters import slugify
from django.db.models import signals
from django.dispatch import dispatcher
from django.core import template_loader
from django.utils.datastructures import MultiValueDictKeyError
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.generic import list_detail, date_based
from django.conf import settings
from django.core.urlresolvers import reverse

import datetime
import mx.DateTime
import re
import string
from StringIO import StringIO
from reportlab.pdfgen.canvas import Canvas
import ldap
from copy import deepcopy


from intranet.org.models import UserProfile, Project, Category
from intranet.org.models import Place, Event, Shopping, Person, Sodelovanje, TipSodelovanja
from intranet.org.models import Task, Diary, Bug, StickyNote, Lend, Resolution, Comment
from intranet.org.models import KbCategory, KB, Tag, Scratchpad, Clipping, Mercenary
from intranet.org.forms import *
from xls import salary_xls

month_dict = { 'jan': 1, 'feb': 2, 'mar': 3,
               'apr': 4, 'maj': 5, 'jun': 6,
               'jul': 7, 'avg': 8, 'sep': 9,
            'okt': 10, 'nov': 11, 'dec': 12, }

# ------------------------------------

def index(request):
    today = datetime.datetime.today()
    nextday = today + datetime.timedelta(days=8)

    if request.user.get_profile().project.all():

        q = Q()
        for i in request.user.get_profile().project.all(): 
            q = q | Q(project=i)

        project_bugs = Bug.objects.filter(q, resolution__resolved=False)

    else:
        project_bugs = None

    return render_to_response('org/index.html',
                              { 'start_date': today,
                                'end_date': nextday,
                                'today': today,
                                'project_bugs': project_bugs,
                                'diary_form': DiaryForm(),
                                'diary_edit': False,
                                'bug_form': BugForm(),
                                'bug_edit': False,
                                'lend_form': LendForm(),
                                'lend_edit': False,
                              },
                              context_instance=RequestContext(request))
index = login_required(index)

def search(request):
    if request.POST:
        query = request.POST.get('term','')

        kategorije = Category.objects.all()
        kb = KB.objects.all()
        users = User.objects.all()
        events = Event.objects.all()

        for term in query.split():
            kb = kb.filter(content__icontains=term)
            kb = kb.filter(title__icontains=term)
            #kb = kb.filter(KbCategory__icontains=term)
        for term in query.split():
            events = events.filter(announce__icontains=term)
            #events = events.filter(category__icontains=term)
        for term in query.split():
            users = users.filter(name__icontains=term)
        for term in query.split():
            kategorije = kategorije.filter(name__icontains=term)

        objects = list(set(events) | set(kb))
        related = []

        return render_to_response('org/search_results.html', {
                                    'object_list': objects,
                                    'search_term': query,
                                })
    else:
        return HttpResponseRedirect("/intranet/")

def lend_back(request, id=None):
    lend = get_object_or_404(Lend, pk=id)
    if not lend.note:
        lend.note = ""
    bug = Bug.objects.get(name=lend.what)
    bug.resolution = Resolution.objects.get(pk=5) #FIXED
    bug.save()
    lend.note += "\n\n---\nvrnitev potrdil %s, %s " % (request.user, datetime.date.today())
    lend.returned = True
    lend.save()
    return HttpResponseRedirect('../')
lend_back = login_required(lend_back)

def lends(request):
    if request.method == 'POST':     
        form = LendForm(request.POST)
        if form.is_valid():
            new_lend = form.save()
            if not form.cleaned_data.has_key('due_date'):
                new_lend.due_date = datetime.datetime.today() + datetime.timedelta(7)

            return HttpResponseRedirect(new_lend.get_absolute_url())
    else:
        form = LendForm()

    return date_based.archive_index(request, 
        queryset = Lend.objects.all().order_by('due_date'),
        date_field = 'from_date',
        allow_empty = 1,
        extra_context = {
            'form': form,
        },
    )
lends= login_required(lends)

def lends_form(request, id=None, action=None):
    #process the add/edit requests, redirect to full url if successful, display form with errors if not.
    if request.method == 'POST':
        if id:
            lend_form = LendForm(request.POST, instance=Lend.objects.get(id=id))
        else:
            lend_form = LendForm(request.POST)

        if lend_form.is_valid():
            lend = lend_form.save()
            new_bug = Bug(author=request.user, due_by = lend.due_date, name=lend.what, note='treba je vrnit %s, see: %s!' % (lend.what, lend.get_absolute_url()))
            new_bug.save()
            new_bug.assign.add(lend.from_who)
            new_bug.save()
            return HttpResponseRedirect(lend.get_absolute_url())
    else:
        if id:
            lend_form = LendForm(instance=Lend.objects.get(id=id))
        else:
            lend_form = LendForm()

    return render_to_response('org/lend.html', {
        'lend_form': lend_form,
        'lend_edit': True,
        }, context_instance=RequestContext(request)
    )
lends_form = login_required(lends_form)

def lend_detail(request, object_id):
    return list_detail.object_detail(request, 
        object_id = object_id, 
        queryset = Lend.objects.all(), 
        extra_context = { 
            'lend_form': LendForm(instance=Lend.objects.get(id=object_id)),
            'lend_edit': True,
        })
lend_detail = login_required(lend_detail)

def lends_by_user(request, username):
    responsible = []
    for l in Lend.objects.filter(returned=False):
        if l.from_who not in responsible:
            responsible.append(l.from_who)
    user = User.objects.get(username__exact=username)
    lend_list = Lend.objects.filter(returned__exact=False).filter(from_who__exact=user)
    return render_to_response('org/lend_archive.html',
                              { 'latest': lend_list,
                                'responsible': responsible,
                              },
                              context_instance=RequestContext(request))
lends_by_user = login_required(lends_by_user)

################################################################################

def shoppings_form(request, id=None, action=None):
    #process the add/edit requests, redirect to full url if successful, display form with errors if not.
    if request.method == 'POST':
        if id:
            shopping_form = ShoppingForm(request.POST, instance=Shopping.objects.get(pk=id))
        else:
            shopping_form = ShoppingForm(request.POST)

        if shopping_form.is_valid():
            shopping = shopping_form.save(commit=False)
            shopping.author = request.user
            shopping.save()
            return HttpResponseRedirect(shopping.get_absolute_url())
    else:
        if id:
            shopping_form = ShoppingForm(instance=shopping.objects.get(id=id))
        else:
            shopping_form = ShoppingForm()

    return render_to_response('org/shopping.html', {
        'shopping_form': shopping_form,
        'shopping_edit': True,
        }, context_instance=RequestContext(request)
    )
shoppings_form = login_required(shoppings_form)

def shopping_by_cost(request, cost):
    list = Shopping.objects.filter(bought__exact=False)
    if int(cost) == 1:
        list = list.filter(cost__lte=1000)
    elif int(cost) == 2:
        list = list.filter(cost__range=(1000, 10000))
    elif int(cost) == 3:
        list = list.filter(cost__range=(10000, 20000))
    elif int(cost) == 4:
        list = list.filter(cost__range=(20000, 50000))
    elif int(cost) == 5:
        list = list.filter(cost__gte=50000)
    else:
        list = []
    return render_to_response('org/shopping_archive.html',
                              { 'latest': list,
                              },
                              context_instance=RequestContext(request))
shopping_by_cost = login_required(shopping_by_cost)

def shopping_index(request):
    wishes = Shopping.objects.filter(bought=False)
    return render_to_response('org/shopping_index.html',
                              { 'wishes': wishes,
                              'shopping_form': ShoppingForm(),
                              'shopping_edit': False,
                              },
                              context_instance=RequestContext(request))
shopping_index = login_required(shopping_index)

def shopping_by_user(request, user):
    user = get_object_or_404(User, pk=user)
    lend_list = Shopping.objects.filter(bought__exact=False).filter(author__exact=user)
    return render_to_response('org/shopping_archive.html',
                              { 'latest': lend_list,
                              },
                              context_instance=RequestContext(request))
shopping_by_user = login_required(shopping_by_user)

def shopping_by_project(request, project):
    project = get_object_or_404(Project, pk=project)
    lend_list = Shopping.objects.filter(bought__exact=False).filter(task__exact=project)
    return render_to_response('org/shopping_archive.html',
                              { 'latest': lend_list,
                              },
                              context_instance=RequestContext(request))
shopping_by_project = login_required(shopping_by_project)

def shopping_by_task(request, task):
    task = get_object_or_404(Task, pk=task)
    lend_list = Shopping.objects.filter(bought__exact=False).filter(project__exact=task)
    return render_to_response('org/shopping_archive.html',
                              { 'latest': lend_list,
                              },
                              context_instance=RequestContext(request))
shopping_by_task = login_required(shopping_by_task)

def stats(request):
    return render_to_response('org/stats.html',
                              { 'today': datetime.date.today() },
                              context_instance=RequestContext(request))
stats = login_required(stats)

def text_log(request):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    tomorow = today + datetime.timedelta(days=2)

    dnevniki = Diary.objects.filter(pub_date__range=(yesterday, today))
    reverzi = Lend.objects.filter(returned__exact=False).filter(due_date__lte=(tomorow))
    dogodki = Event.objects.filter(start_date__range=(today, tomorow))
    novo = Event.objects.filter(pub_date__range=(yesterday, today))
    dogodki_vceraj = Event.objects.filter(start_date__range=(yesterday, today))
    scratchpad = Scratchpad.objects.latest('id')
    return render_to_response('feeds/nightly_report.html',
                              { 'today': today,
                                'dnevniki': dnevniki,
                                'reverzi': reverzi,
                                'dogodki': dogodki,
                                'novo': novo,
                                'dogodki_vceraj': dogodki_vceraj,
                                'scratchpad': scratchpad,
                              },
                              context_instance=RequestContext(request))

# ------------------------------------

def process_cloud_tag(instance):
    ''' distribution algo n tags to b bucket, where b represents
    font size. '''
    entry = instance
    # be sure you save twice the same entry, otherwise it wont update the new tags.
    entry_tag_list = entry.tags.all()
    for tag in entry_tag_list:
        tag.total_ref = tag.entry_set.all().count();
        tag.save()

    tag_list = Tag.objects.all()
    nbr_of_buckets = 8
    base_font_size = 11
    tresholds = []
    max_tag = max(tag_list)
    min_tag = min(tag_list)
    delta = (float(max_tag.total_ref) - float(min_tag.total_ref)) / (float(nbr_of_buckets))
    # set a treshold for all buckets
    for i in range(nbr_of_buckets):
        tresh_value =  float(min_tag.total_ref) + (i+1) * delta
        tresholds.append(tresh_value)
    # set font size for tags (per bucket)
    for tag in tag_list:
        font_set_flag = False
        for bucket in range(nbr_of_buckets):
            if font_set_flag == False:
                if (tag.total_ref <= tresholds[bucket]):
                    tag.font_size = base_font_size + bucket * 2
                    tag.save()
                    font_set_flag = True

# connect signal
#dispatcher.connect(process_cloud_tag, sender = Event, signal = signals.post_save)

##################################################

def diarys_form(request, id=None, action=None):
    if request.method == 'POST':
        if id:
            diary_form = DiaryForm(request.POST, instance=Diary.objects.get(id=id))
        else:
            diary_form = DiaryForm(request.POST)

        if diary_form.is_valid():
            diary = diary_form.save(commit=False)
            diary.author = request.user
            diary.save()
            return HttpResponseRedirect(diary.get_absolute_url())
    else:
        if id:
            diary_form = DiaryForm(instance=Diary.objects.get(id=id))
        else:
            diary_form = DiaryForm()

    return render_to_response('org/diary.html', {
        'diary_form': diary_form,
        'diary_edit': True,
        }, context_instance=RequestContext(request)
    )
diarys_form = login_required(diarys_form)

def diarys(request):
    diarys = Diary.objects.all()
    if request.POST:
        filter = DiaryFilter(request.POST)
        if filter.is_valid():
            for key, value in filter.cleaned_data.items():
                if value:
                    ##'**' rabis zato da ti python resolva spremenljivke (as opposed da passa dobesedni string)
                    diarys = diarys.filter(**{key: value})
    else:
        filter = DiaryFilter()

    return date_based.archive_index(request, 
        queryset = diarys.order_by('date'),
        date_field = 'date',
        allow_empty = 1,
        extra_context = {
            'filter': filter,
            'diary_form': DiaryForm(),
        }
    )
diarys = login_required(diarys)

def diary_detail(request, object_id):
    return list_detail.object_detail(request, 
        object_id = object_id, 
        queryset = Diary.objects.all(), 
        extra_context = { 
            #the next line is the reason for wrapper function, dunno how to 
            #pass generic view dynamic form.
            'diary_form': DiaryForm(instance=Diary.objects.get(id=object_id)),
            'diary_edit': True,
        })
diary_detail = login_required(diary_detail)


##################################################


# dodaj podatek o obiskovalcih dogodka
def shopping_buy (request, id=None):
    event = get_object_or_404(Shopping, pk=id)
    event.bought = True
    event.save()
    return HttpResponseRedirect('../')
shopping_buy = login_required(shopping_buy)

def shopping_support (request, id=None):
    wish = get_object_or_404(Shopping, pk=id)
    wish.supporters.add(request.user)
    wish.save()
    return HttpResponseRedirect(wish.get_absolute_url())
shopping_support = login_required(shopping_support)

def shopping_detail(request, object_id):
    return list_detail.object_detail(request, 
        object_id = object_id, 
        queryset = Shopping.objects.all(), 
        extra_context = { 
            #the next line is the reason for wrapper function, dunno how to 
            #pass generic view dynamic form.
            'shopping_form': ShoppingForm(instance=Shopping.objects.get(id=object_id)),
            'shopping_edit': True,
        })
shopping_detail = login_required(shopping_detail)

##################################################

def autocomplete(request, search):
    output = StringIO()
    if request.GET.has_key('q'):
        search = request.GET['q']
    for i in Person.objects.filter(name__icontains=search):
        output.write('%s\n' % i)
    response = HttpResponse(mimetype='text/plain')
    response.write(output.getvalue())
    return response


#################################################

def issues(request):
    bugs = Bug.objects.all()
    if request.POST:
        filter = FilterBug(request.POST)
        if filter.is_valid():
            for key, value in filter.cleaned_data.items():
                if value:
                    if key == 'name':
                        bugs = bugs.filter(name__icontains = value)
                    else:
                        ##'**' rabis zato da ti python resolva spremenljivke (as opposed da passa dobesedni string)
                        bugs = bugs.filter(**{key: value})
    else:
        bugs = bugs.filter(assign=request.user, resolution__resolved=False)
        filter = FilterBug()

    return date_based.archive_index(request, 
        queryset = bugs.order_by('chg_date'),
        date_field = 'pub_date',
        allow_empty = 1,
        extra_context = {
            'filter': filter,
            'bug_form': BugForm(),
        }
    )
issues = login_required(issues)

def resolve_bug(request, id):
    bug = Bug.objects.get(pk=id)
    bug.resolution = Resolution.objects.get(pk=5) #FIXED
    bug.save()
    return  HttpResponseRedirect('..')
resolve_bug = login_required(resolve_bug)

def add_bug(request):
    if request.POST:
        form = BugForm(request.POST)
        if form.is_valid():
            new_bug = form.save(commit=False)
            new_bug.author = request.user
            new_bug.save()
            form.save_m2m()
            new_bug.mail()
            return HttpResponseRedirect(new_bug.get_absolute_url())

    return HttpResponseRedirect("..")
add_bug = login_required(add_bug)


##################################################

def comment_add(request, bug_id):
    bug = Bug.objects.get(pk=bug_id)
    if request.method == 'POST':
        form = CommentBug(request.POST)
        if form.is_valid():
            new_comment = Comment(bug=bug, text=form.cleaned_data['text'])
            new_comment.save(request)
        bug.mail(message=new_comment.text, subject='new comment has been added to #' + bug.id.__str__())
    
    return HttpResponseRedirect(bug.get_absolute_url())

def bug_edit(request, bug_id):
    bug = Bug.objects.get(pk=bug_id)
    if request.method == 'POST':
        form = BugForm(request.POST, instance=bug)
        if form.is_valid():
            old = deepcopy(bug)
            form.save()
            bug.save()
            message = ''
            for (i, j) in bug.__dict__.items():
                try:
                    if bug.__dict__[i] != old.__dict__[i] and i != 'chg_date':
                        message += '- %s changed from "%s" to "%s"\n' % (i, old.__dict__[i], bug.__dict__[i])
                except KeyError:
                    pass
            bug.mail(subject='#%d has been edited' % bug.id, message=message)
    return HttpResponseRedirect(bug.get_absolute_url())

def bug_subtask(request, bug_id):
    bug = Bug.objects.get(pk=bug_id)
    if request.method == 'POST':
        form = BugForm(request.POST)
        if form.is_valid():
            new_bug = form.save(commit=False)
            new_bug.parent = bug
            new_bug.author = request.user
            new_bug.save()
            form.save_m2m()
            return HttpResponseRedirect(new_bug.get_absolute_url())

    return HttpResponseRedirect(bug.get_absolute_url())



def view_bug(request, object_id):
    comment_form = CommentBug()
    bug_form = BugForm(instance=Bug.objects.get(pk=object_id))
    subtask_form = BugForm()

    return list_detail.object_detail(request, 
        object_id = object_id, 
        queryset = Bug.objects.all(), 
        extra_context = { 
            'resolutions': Resolution.objects.all(), 
            'comments': Comment.objects.all(), 
            'comment_form': comment_form.as_p(), 
            'bug_form': bug_form,
            'bug_edit': True,
            'subtask_form': subtask_form.as_p(),
        })
view_bug = login_required(view_bug)

##################################################
def events(request):
    events = Event.objects.all()
    filtered = False
    if request.POST:
        filter = EventFilter(request.POST)
        if filter.is_valid():
            for key, value in filter.cleaned_data.items():
                if value:
                    filtered = True
                    if key == 'title':
                        events = events.filter(title__icontains = value)
                    else:
                        ##'**' rabis zato da ti python resolva spremenljivke (as opposed da passa dobesedni string)
                        events = events.filter(**{key: value})
    else:
        filter = EventFilter()

    today = datetime.datetime.today()
    while today.weekday() != 0:
        today = today - datetime.timedelta(1)

    week = datetime.timedelta(7)
    return date_based.archive_index(request, 
        queryset = events,
        date_field = 'start_date',
        allow_empty = 1,
        extra_context = {
            'filter': filter,
            'filtered': filtered,
            'events': events,
            'event_last': Event.objects.filter(start_date__lte=today, start_date__gt=today-week).order_by('start_date'),
            'event_this': Event.objects.filter(start_date__lte=today+week, start_date__gt=today).order_by('start_date'),
            'event_next': Event.objects.filter(start_date__lte=today+2*week, start_date__gt=today+week).order_by('start_date'),
            'event_next2': Event.objects.filter(start_date__lte=today+3*week, start_date__gt=today+2*week).order_by('start_date'),
            'years': range(2006, datetime.datetime.today().year+1),
        },
    )
events = login_required(events)

def nf_event_create(request):
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES)
        authors = zip(request.POST.getlist('author'), request.POST.getlist('tip'))
    else:
        form = EventForm()


    if form.is_valid():
        new_event = form.save()
        for author, tip in authors:
            tip = TipSodelovanja.objects.get(pk=tip)
            #make sure the Person actually exists 
            try: 
                person = Person.objects.get(name=author) 
            except Person.DoesNotExist: 
                person = Person(name=author) 
                person.save() 

            s = Sodelovanje(event=new_event, tip=tip, person=person)
            s.save() 
        new_event.slug = slugify(new_event.title)
        new_event.save()
        return HttpResponseRedirect(new_event.get_absolute_url())

    return render_to_response('org/nf_event.html', {'form': form, 'tipi': TipSodelovanja.objects.all()},
        context_instance=RequestContext(request))
nf_event_create = login_required(nf_event_create)

def nf_event_edit(request, event):
    event = Event.objects.get(pk=event)
    old_sodelovanja = set(Sodelovanje.objects.filter(event=event))
    if request.method == 'POST':
        form = EventForm(request.POST, request.FILES, instance=event)
        authors = zip(request.POST.getlist('author'), request.POST.getlist('tip'))

        if form.is_valid():
            new_event = form.save()
            sodelovanja = set()
            for author, tip in authors:
                tip = TipSodelovanja.objects.get(pk=tip)
                #make sure the Person actually exists 
                try: 
                    person = Person.objects.get(name=author) 
                except Person.DoesNotExist: 
                    person = Person(name=author) 
                    person.save() 


                try:
                    s = Sodelovanje.objects.get(event=new_event, person=person, tip=tip)
                except Sodelovanje.DoesNotExist:
                    s = Sodelovanje(event=new_event, tip=tip, person=person)
                    s.save() 
                
                sodelovanja.add(s)


            new_event.slug = slugify(new_event.title)
            new_event.save()

            #delete everything that was in the old sodelovanja as is not in the new one
            for i in old_sodelovanja & sodelovanja ^ old_sodelovanja:
                i.delete()

            return HttpResponseRedirect(new_event.get_absolute_url())
    else:
        form = EventForm(instance=event)




    return render_to_response('org/nf_event.html', {'form': form, 'tipi': TipSodelovanja.objects.all(), 
        'sodelovanja': Sodelovanje.objects.filter(event=event)}, 
        context_instance=RequestContext(request))
nf_event_edit = login_required(nf_event_edit)

def event(request, object_id):
    return list_detail.object_detail(request,
        queryset = Event.objects.all(),
        object_id = object_id,
        extra_context =  {
            'sodelovanja': Sodelovanje.objects.filter(event=object_id)
        }
    )
event = login_required(event)

# dodaj podatek o obiskovalcih dogodka
def event_count (request, id=None):
    event = get_object_or_404(Event, pk=id)
    event.visitors = int(request.POST['visitors'])
    event.save()
    return HttpResponseRedirect('../')
event_count = login_required(event_count)

##############################

def _get_begin_end(year=None, month=None):
    if year == None:
        year = datetime.datetime.today().year
        month = datetime.datetime.today().month

    year = int(year)
    month = int(month)
    
    begin = datetime.datetime(year, month, 1)
    if month == 12:
        next = 1
    else:
        next = month+1

    end = begin.replace(month=next)
    return (begin, end)

def _get_mercenaries(year=None, month=None):
    begin, end = _get_begin_end(year, month)
    mercenaries = {}
    for i in Mercenary.objects.all():
        #find the one that was active at the requested time
        history = i.history.all()
        count = i.history.count()-1
        for j in range(0, count+1):
            if j == count:
                i = history[count]
            else:
                if j == 0:
                    if end > history[j]._audit_timestamp:
                        i = history[j]
                        break
                if (history[j]._audit_timestamp > end) and (end > history[j+1]._audit_timestamp):
                    i = history[j+1]
                    break

        try:
            mercenaries[i.person]
        except KeyError:
            mercenaries[i.person] = 0

        mercenaries[i.person] += i.amount


    for i in Diary.objects.filter(task__salary_rate__isnull = False, date__gte=begin, date__lt=end):
        try:
            mercenaries[i.author]
        except KeyError:
            mercenaries[i.author] = 0
       
        salary_rate = i.task.salary_rate
        history = i.task.history.all()
        count = i.task.history.count()-1
        for j in range(0, count+1):
            if j == count:
                salary_rate = history[count].salary_rate
                break
            else:
                if j == 0:
                    if end > history[j]._audit_timestamp:
                        salary_rate = history[j].salary_rate
                        break
                if (history[j]._audit_timestamp > end) and (end > history[j+1]._audit_timestamp):
                    salary_rate = history[j+1].salary_rate
                    break

        mercenaries[i.author] += i.length.hour * salary_rate

    return mercenaries

def mercenaries(request, year = None, month=None):
    if year == None:
        return HttpResponseRedirect('%s/%s/' % (datetime.datetime.today().year, datetime.datetime.today().month))

    mercenaries = _get_mercenaries(year, month)
    all = 0
    for m in mercenaries:
        all += mercenaries[m]


    return render_to_response('org/mercenaries.html', 
        {'add_link': '%s/intranet/admin/org/mercenary/add/' % settings.BASE_URL,
        'mercenaries': mercenaries, 'year': year, 'month': month, 'all': all, 
        'hmonth': datetime.datetime(int(year), int(month), 1).strftime('%B')},
        context_instance=RequestContext(request))
mercenaries = login_required(mercenaries)

def mercenary_salary(request, year, month, id):
    mercenaries = []
    begin, end = _get_begin_end(year, month)
    output = StringIO()
    params = []
    if id == 'compact':
        compact = True
    else:
        compact = False

    if id == 'vsi' or id == 'compact':
        for i in _get_mercenaries(year, month):
            mercenaries.append(i)
        filename = 'place_%d_%d' % (begin.month, begin.year)
        if compact:
            filename = 'compact_place_%d_%d' % (begin.month, begin.year)
    else:
       mercenaries.append(User.objects.get(pk=id))
       filename = unicode(mercenaries[0])

    for mercenary in mercenaries:
        try:
            m = Mercenary.objects.get(person=mercenary)
            params.append({'mercenary': mercenary.get_full_name(),
                    'amount':  _get_mercenaries(year, month)[mercenary],
                    'cost_center': unicode(m.cost_center),
                    'salary_type':  unicode(m.salary_type),
                    'description': unicode(m.description),
                    })
        except Mercenary.DoesNotExist:
            hours = 0
            for d in Diary.objects.filter(author=mercenary, date__gte=begin, date__lt=end):
                hours += d.length.hour
            project = d.task
            params.append({'mercenary': mercenary.get_full_name(),
                    'amount':  _get_mercenaries(year, month)[mercenary],
                    'cost_center': unicode(project.cost_center),
                    'salary_type':  unicode(project.salary_type),
                    'hours': hours,
                    'description': unicode(project),
                    })
    
    output.write(salary_xls(compact=compact, bureaucrat=request.user.get_full_name(), params=params))

    response = HttpResponse(mimetype='application/octet-stream')
    response['Content-Disposition'] = "attachment; filename=" + filename + '.xls'
    response.write(output.getvalue())
    return response
mercenary_salary = login_required(mercenary_salary)

##################################################

def person(request):
    if request.method == 'POST':
        form = PersonForm(request.POST)
        if form.is_valid():
            person = Person(name=form.cleaned_data['name'])
            person.save()
            for key, value in form.cleaned_data.items():
                if not value or key == 'name':
                    continue

                clas = key[0].capitalize() + key[1:]
                exec 'from intranet.org.models import ' + clas
                for k in request.POST.getlist(key):
                    new_var = locals()[clas](**{key: k})
                    new_var.save()
                    Person.__dict__[key].__get__(person, clas).add(new_var)

    return HttpResponseRedirect('../')

def sodelovanja(request):
    sodelovanja = Sodelovanje.objects.all()
    person_form = PersonForm()
    if request.method == 'POST':
        form = SodelovanjeFilter(request.POST)
        if form.is_valid():
            for key, value in form.cleaned_data.items():
                ##'**' rabis zato da ti python resolva spremenljivke (as opposed da passa dobesedni string)
                if value and key != 'export':
                    sodelovanja = sodelovanja.filter(**{key: value})

    else:
        form = SodelovanjeFilter()

    try: 
        export =  form.cleaned_data['export']
        if export:
            output = StringIO()
            if export == 'txt':
                for i in sodelovanja:
                    output.write("%s\n" % i)
            elif export == 'pdf':
                pdf = Canvas(output)
                rhyme = pdf.beginText(30, 200)
                for i in sodelovanja:
                    rhyme.textLine(i.__unicode__())
                pdf.drawText(rhyme)
                pdf.showPage()
                pdf.save()
            elif export == 'csv':
                for i in sodelovanja:
                    output.write("%s\n" % i)

                    
            response = HttpResponse(mimetype='application/octet-stream')
            response['Content-Disposition'] = "attachment; filename=" + 'export.' + export
            response.write(output.getvalue())
            return response

    except AttributeError:
        pass
    
    return render_to_response('org/sodelovanja.html', 
        {'sodelovanja': sodelovanja, 'form': form, 
        'admin_org': '%s/intranet/admin/org/' % settings.BASE_URL,
        'person_form': person_form },
        context_instance=RequestContext(request))
sodelovanja = login_required(sodelovanja)

def clipping(request):
    clippings = Clipping.objects.all()
    if request.method == 'POST':
        form = ClippingFilter(request.POST)
        if form.is_valid():
            for key, value in form.cleaned_data.items():
                if value and key != 'export':
                    if key == 'medij':
                        ##handle the recursion
                        query = Q(medij=value)
                        for i in value.children():
                            query = query | Q(medij=i)
                        clippings = clippings.filter(query)
                    elif key == 'link' or key == 'rubrika' or key == 'address':
                        #clippings = clippings.filter(link__icontains = value)
                        clippings = clippings.filter(**{key+'__icontains': value})

                    else:
                        clippings = clippings.filter(**{key: value})
    else:
        form = ClippingFilter()

    try: 
        export =  form.cleaned_data['export']
        if export:
            output = StringIO()

###            output = StringIO()
###            if export == 'txt':
###                for i in sodelovanja:
###                    output.write("%s\n" % i)
###            elif export == 'pdf':
###                pdf = Canvas(output)
###                rhyme = pdf.beginText(30, 200)
###                for i in sodelovanja:
###                    rhyme.textLine(i.__unicode__())
###                pdf.drawText(rhyme)
###                pdf.showPage()
###                pdf.save()
###            elif export == 'csv':
###                for i in sodelovanja:
###                    output.write("%s\n" % i)
###
###                    
###            response = HttpResponse(mimetype='application/octet-stream')
###            response['Content-Disposition'] = "attachment; filename=" + 'export.' + export
###            response.write(output.getvalue())
###            return response

    except AttributeError:
        pass

    return render_to_response('org/clipping.html', 
        {'clippings': clippings, 'form': form, 'add_link': '%s/intranet/admin/org/clipping/add/' % settings.BASE_URL },
        context_instance=RequestContext(request))
clipping = login_required(clipping)

##################################################

def tehniki_monthly(request, year=None, month=None):
    user = request.user
    iso_week = mx.DateTime.now().iso_week[1]
    if month:
        month = mx.DateTime.Date(int(year), int(month_dict[month]), 1).month
    else:
        month = mx.DateTime.now().month
    if year:
        year = mx.DateTime.Date(int(year), int(month), 1).year
    else:
        year = mx.DateTime.now().year

    month_start = mx.DateTime.Date(year, month, 1)
    month_end = month_start + mx.DateTime.DateTimeDelta(month_start.days_in_month)

    month_number = month
    month = Event.objects.filter(start_date__range=(month_start, month_end), require_technician__exact=True).order_by('start_date')
    log_list = Diary.objects.filter(task=23, date__range=(month_start, month_end))
    for log in log_list:
      print "Found billable technician log #%s: %s on %s for %s hours" % (log.pk, log.author, log.date, log.length)

    for e in month:
        try:
            diary = e.diary_set.get()
            e.diary = diary.id
            e.diary_length = diary.length
        except:
            e.diary = 0

        try:
            e.tech = e.technician.username
        except:
            e.tech = 0

    navigation = monthly_navigation (year, month_number)

    return render_to_response('org/tehniki_index.html',
                             {'month':month,
                             'log_list':log_list,
                             'month_number':month_number,
                             'month_name': month_to_string(month_number),
                             'what': 'mesec',
                             'iso_week': iso_week,
                             'year': year,
                             'navigation': navigation,
                             'start_date': month_start,
                             'end_date': month_end,
                             'ure': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
                             },
                             context_instance=RequestContext(request)
                             )
tehniki_monthly = login_required(tehniki_monthly)

def monthly_navigation (year=None, month=None):
    month_prev = month - 1
    month_next = month + 1
    year_prev = year
    year_next = year

    if month_prev < 1:
        month_prev = 12
        year_prev = year - 1

    if month_next > 12:
        month_next = 1
        year_next = year + 1

    return {'prev': '%s/%s' % (year_prev, month_to_string(month_prev)),
            'next': '%s/%s' % (year_next, month_to_string(month_next)) }

def month_to_string (month=None):
    for i in month_dict:
        if month_dict[i] == month:
            return i

def weekly_navigation (year=None, week=None, week_start=None, week_end=None):
    week_prev = week - 1
    week_next = week + 1
    year_prev = year
    year_next = year

    if week_prev < 1:
        week_prev = 52
        year_prev = year - 1

    if week_next > 52:
        week_next = 1
        year_next = year + 1

    return {'prev': '%s/%s' % (year_prev, week_prev),
            'next': '%s/%s' % (year_next, week_next) }

def tehniki(request, year=None, week=None):
    user = request.user
    iso_week = mx.DateTime.now().iso_week
    month = mx.DateTime.now().month

    if year:
      year = int(year)
    else:
      year = mx.DateTime.now().year

    if week:
        i = int(week)
    else:
        i = iso_week[1]

    week_start = mx.DateTime.ISO.Week(year, i, 1)
    week_end = mx.DateTime.ISO.Week(year, i, 8)

    week_number = i

    week_now = week_start
    events = Event.objects.filter(start_date__range=(week_start, week_end), require_technician__exact=True).order_by('start_date')
    log_list = Diary.objects.filter(task=23, date__range=(week_start, week_end))

    week = []
    for e in events:
        authors = [a.author for a in e.diary_set.all()]
        non_diary = set(e.technician.all()) - set(authors)
        #(<array of authors of diarys>, event)
        week += [(non_diary, e)]

    navigation = weekly_navigation (year, week_number, week_start, week_end)

    return render_to_response('org/tehniki_index.html',
                             {'month':week,
                             'log_list':log_list,
                             'month_number':week_number,
                             'month_name': month_to_string(month),
                             'what': 'teden',
                             'iso_week': week_number,
                             'year': year,
                             'navigation': navigation,
                             'start_date': week_start,
                             'end_date': week_end,
                             'ure': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
                             },
                             context_instance=RequestContext(request)
                             )
tehniki = login_required(tehniki)

def tehniki_add(request):
    id = request.POST['uniqueSpot']
    if not id:
        return HttpResponseRedirect('../')

    event = Event.objects.get(pk=id)

    p = Diary(      date=event.start_date,
                    event=event,
                    author=request.user,
                    task=Project.objects.get(pk=23),
                    log_formal=request.POST['log_formal'],
                    log_informal=request.POST['log_informal'],
                    length=datetime.time(int(request.POST['length']),0),
                    )
    p.save()

    return HttpResponseRedirect('../')
tehniki_add = login_required(tehniki_add)

def tehniki_take(request, id):
    e = Event.objects.get(pk=id)
    e.technician.add(request.user)
    week = datetime.timedelta(7)
    if e.require_video:
        new_bug = Bug.objects.get_or_create(name = e.title, defaults={'author': request.user})[0]
        new_bug.save()
        new_bug.due_by = e.start_date + week
        new_bug.note='treba je zmontirat in objavit "%s" video!' % e.title
        new_bug.assign.add(request.user)
        new_bug.save()
    e.save()

    return HttpResponseRedirect('../../')
tehniki_take = login_required(tehniki_take)

def tehniki_cancel(request, id):
    e = Event.objects.get(pk=id)
    e.technician.remove(request.user)
    e.save()
    bug = Bug.objects.get(name=e.title)
    bug.assign.remove(request.user)
    bug.save()

    return HttpResponseRedirect('../../')
tehniki_take = login_required(tehniki_take)

def tehniki_text_log(request):
    Date = mx.DateTime.Date
    d = mx.DateTime.now()
    c = mx.DateTime.now() - mx.DateTime.oneDay

    f = mx.DateTime.Date(c.year, c.month, c.day)
    g = mx.DateTime.Date(d.year, d.month, d.day)

    log_list = Diary.objects.filter(task__pk=2, date__range=(f, g))

    return render_to_response('org/dezuranje_text_log.html', {'log_list':log_list,})

# ---
def dezurni_monthly(request, year=None, month=None):
    iso_week = mx.DateTime.now().iso_week
# doloci mesec pregledovanja
    if year:
        year = mx.DateTime.Date(int(year), int(month_dict[month]), 1).year
    else:
        year = mx.DateTime.now().year

    if month:
        month = mx.DateTime.Date(int(year), int(month_dict[month]), 1).month
    else:
        month = mx.DateTime.now().month

    month_start = mx.DateTime.Date(year, month, 1)
    month_end = month_start + mx.DateTime.DateTimeDelta(month_start.days_in_month)

    month_prev = month - 1
    month_next = month + 1
    month_number = month

    month_now = month_start
    month = []

    while month_now < month_end:
        dict = {}
        dict['date'] = month_now.strftime('%d.%m. %a')

        dict['dezurni'] = []

        Time = mx.DateTime.Time

#        for i in [Time(hours=10), Time(hours=13), Time(hours=16), Time(hours=19)]:
#        for i in [Time(hours=11), Time(hours=16)]:
        for i in [Time(hours=10), Time(hours=14), Time(hours=18)]:
            dezurni_list = Diary.objects.filter(task=22, date__range=(month_now+i, month_now+i+Time(3.59))).order_by('date')
            dezurni_dict = {}
            if dezurni_list:
                dezurni_obj = dezurni_list[0]
                dezurni_dict['name'] = dezurni_obj.author
                dezurni_dict['admin_id'] = dezurni_obj.id
            else:
                dezurni_dict['unique'] = (month_now+i).strftime('%d.%m.%y-%H:%M')
                dezurni_dict['name'] = None
            dict['dezurni'].append(dezurni_dict)

        month.append(dict)
        month_now = month_now + mx.DateTime.oneDay

    log_list = Diary.objects.filter(task=22, date__range=(month_start, month_end)).order_by('-date')

    navigation = monthly_navigation (year, month_number)

    return render_to_response('org/dezuranje_monthly.html',
                                        {'month':month,
                                        'log_list':log_list,
                                        'year': year,
                                        'iso_week': iso_week[1],
                                        'month_name': month_to_string(month),
                                        'navigation':navigation,
                                        'month_number':month_number,
                                        'start_date': month_start,
                                        'end_date': month_end,
                                        },
                              context_instance=RequestContext(request))
dezurni_monthly = login_required(dezurni_monthly)

def dezurni(request, year=None, week=None, month=None):
    iso_week = mx.DateTime.now().iso_week
    month = mx.DateTime.now().month

    if year:
      year = int(year)
    else:
      year = mx.DateTime.now().year

    if week:
        i = int(week)
    else:
        i = iso_week[1]

    week_start = mx.DateTime.ISO.Week(year, i, 1)
    week_end = mx.DateTime.ISO.Week(year, i, 6)

    week_prev = i - 1
    week_next = i + 1
    week_number = i

    week_now = week_start
    week = []

    while week_now < week_end:
        dict = {}
        dict['date'] = week_now.strftime('%d.%m. %a')
        dict['dezurni'] = []

	Time = mx.DateTime.Time

	###od tega datuma naprej velja nov urnik
	if mx.DateTime.Date(2008, 04, 14) <= week_start and mx.DateTime.Date(2008, 9, 14) > week_start:
		nov_urnik = 1
		time_list = [Time(11), Time(16)]
	elif mx.DateTime.Date(2008, 9, 14) <= week_start:
		nov_urnik = 2
		time_list = [Time(10), Time(14), Time(18)]
	else:
		nov_urnik = 0
		time_list = [Time(10), Time(13), Time(16), Time(19)]
    

        for i in time_list:
            dezurni_list = Diary.objects.filter(task=22, date__range=(week_now+i, week_now+i+Time(2.59))).order_by('date')
            dezurni_dict = {}
            if dezurni_list:
                dezurni_obj = dezurni_list[0]
                dezurni_dict['name'] = dezurni_obj.author
                dezurni_dict['admin_id'] = dezurni_obj.id
            else:
                dezurni_dict['unique'] = (week_now+i).strftime('%d.%m.%y-%H:%M')
                dezurni_dict['name'] = None
            dict['dezurni'].append(dezurni_dict)

        week.append(dict)
        week_now = week_now + mx.DateTime.oneDay

    log_list = Diary.objects.filter(task__pk=22, date__range=(week_start, week_end)).order_by('-date')
    navigation = weekly_navigation (year, week_number, week_start, week_end)
    return render_to_response('org/dezuranje_index.html',
                             {'week': week,
                             'iso_week': week_number,
                             'month_name': month_to_string(month),
                             'log_list':log_list,
                             'navigation':navigation,
                             'year': year,
                             'iso_week': week_number,
			     			 'week_number':week_number,
                             'nov_urnik': nov_urnik,
                             'start_date': week_start,
                             'end_date': week_end,
                             'dezurni_taski': Bug.objects.filter(project=Project.objects.get(pk=22)), 
                             },
                       context_instance=RequestContext(request))
dezurni = login_required(dezurni)

def dezurni_add(request):
    new_data = request.POST.copy()
    if not request.POST or not new_data.has_key('uniqueSpot'):
        return HttpResponseRedirect('../')

    d = mx.DateTime.DateTimeFrom(request.POST['uniqueSpot'].__str__())
    datum = datetime.datetime(year=d.year,
                              month=d.month,
                              day=d.day,
                              hour=d.hour,
                              minute=d.minute,
                              second=0,
                              microsecond=0)

    p = Diary(date=datum,
              author=request.user,
              task=Project.objects.get(pk=22),
              log_formal=request.POST['log_formal'],
              log_informal=request.POST['log_informal'],)
    p.save()
    return HttpResponseRedirect('../')
dezurni_add = login_required(dezurni_add)




##################################################

def kb_index(request):
    object_list = KbCategory.objects.all()
    return render_to_response('org/kb_index.html',
                              {'object_list':object_list,},
                              context_instance=RequestContext(request))
kb_index = login_required(kb_index)

def kb_article(request, kbcat, article):
    article = get_object_or_404(KB, slug=article)
    return render_to_response('org/kb_article.html',
                              {'article':article,},
                              context_instance=RequestContext(request))
kb_article = login_required(kb_article)

def imenik(request):
    profile = UserProfile.objects.get(user=request.user) 
    pipec_form = PipecForm(instance=profile, prefix='pipec', initial={'email': request.user.email, 'first_name': request.user.first_name, 'last_name': request.user.last_name})

    change_pass_message = ''
    changepw = ChangePw(prefix='changepw')

    folks = UserProfile.objects.filter(user__is_active__exact=True)
    filter = ImenikFilter(prefix='filter')

    if request.POST:
        #figure out which form was submited
        for key in request.POST:
            pipec = re.compile('^pipec')
            chgpw = re.compile('^changepw')
            imenik_filter = re.compile('^filter')
            if  pipec.match(key):
                pipec_form = PipecForm(request.POST, instance=profile, prefix='pipec')
                break
            elif chgpw.match(key):
                changepw = ChangePw(request.POST, prefix='changepw')
                break
            elif imenik_filter.match(key):
                filter = ImenikFilter(request.POST, prefix='filter')
                break

        if filter.is_valid():
            for key, value in filter.cleaned_data.items():
                if key == 'project' and value:
                    ##handle the recursion
                    query = Q(project=value)
                    for i in value.children():
                        query = query | Q(project=i)

                    folks = UserProfile.objects.filter(query).distinct().select_related('user')
        
        if changepw.is_valid():
            #some additional custom error checking
            if changepw.cleaned_data['newpass1'] == changepw.cleaned_data['newpass2']:
                change_pass_message = 'congrats, changed your pass'
                try:
                    l = ldap.initialize(settings.LDAP_SERVER)
                    dn = 'uid=%s,ou=people,dc=kiberpipa,dc=org' % request.user.username
                    l.simple_bind_s(dn, changepw.cleaned_data['oldpass'])
                    l.passwd_s(dn, changepw.cleaned_data['oldpass'], changepw.cleaned_data['newpass1'])
                except ldap.SERVER_DOWN:
                    change_pass_message = 'uggghhh, ldap server down???'
                except ldap.CONSTRAINT_VIOLATION, e:
                    change_pass_message = e[0]['info']
                except ldap.INVALID_CREDENTIALS:
                    change_pass_message = 'sorry buddy, wrong password'
            else:
                change_pass_message = 'sorry, the two new passwords don\'t match'

        if pipec_form.is_valid():
            request.user.email = pipec_form.cleaned_data['email']
            request.user.first_name = pipec_form.cleaned_data['first_name']
            request.user.last_name = pipec_form.cleaned_data['last_name']
            request.user.save()
            pipec_form.save()

               

    return list_detail.object_list(request, 
        queryset = folks,
        template_name = 'org/imenik_list.html',
        extra_context = {
            'filter': filter,
            'pipec_form': pipec_form,
            'change_pass': changepw,
            'change_pass_message': change_pass_message,
        })

imenik = login_required(imenik)

def timeline_xml(request):
  #diary_list = Diary.objects.filter(task__id__gt=2)
  event_list = Event.objects.all()
  t = template_loader.get_template("org/timeline_xml.html")
  c = Context({'event_list': event_list})
  return HttpResponse(t.render(c), 'application/xml')

def scratchpad_change(request):
    if request.POST:
        scratchpad = Scratchpad.objects.latest('id')
        scratchpad.author = request.user
        scratchpad.content = request.POST['content']
        scratchpad.save()
    return HttpResponseRedirect("/intranet/")
scratchpad_change = login_required(scratchpad_change)

