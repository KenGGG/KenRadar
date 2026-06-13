---
type: video_note
platform: "抖音"
creator: "Simon林"
creator_id: "MS4wLjABAAAACsVvwoWhwaNZkd4kOY7bu6UhcfCiYmd_k_wcUnN9bYo8jOANJ1iyts7MXQB8nsZ0"
video_id: "7635300611730246946"
source_url: "https://www.douyin.com/video/7635300611730246946"
original_title: "Claude Code操控浏览器，最省Token的一条路 Browser Harness：一根 WebSocket 直连浏览器内核 \n#claude #claudecode #browserharness"
title: "Browser Harness：通过WebSocket直连Chrome内核，实现"
published_at: "2026-05-02 22:26:11"
ai_model: "agnes-2.0-flash"
transcript_model: "large-v3-turbo"
topics:
  - "AI工具"
  - "自动化"
  - "浏览器自动化"
  - "开源项目"
  - "效率优化"
  - "BrowserHarness"
  - "AI操控浏览器"
  - "低Token消耗"
  - "WebSocket"
  - "CDP"
tags:
  - "KenRadar"
  - "视频笔记"
  - "抖音"
  - "AI工具"
  - "自动化"
  - "浏览器自动化"
  - "开源项目"
  - "效率优化"
  - "BrowserHarness"
  - "AI操控浏览器"
status: processed
value_score: 4
---

# Browser Harness：通过WebSocket直连Chrome内核，实现

## 一、内容简述

### （一）一句话结论

> [!summary]
> 视频介绍了一个名为Browser Harness（原文误作brower heys/brother honeys）的开源项目，该项目通过WebSocket直连Chrome内核（CDP），为AI提供低Token消耗的浏览器操控能力。相比Computer Use（截屏模拟，Token爆炸）和Selenium（代码量大），Browser Harness仅几百行代码。

### （二）核心内容

1. **Browser Harness项目概况与优势**  
   Browser Harness是一个近期上线的GitHub仓库，上线15天获得9400个Star，代码量仅约600-800行Python。其核心优势是通过WebSocket直连Chrome内核（CDP），专为AI设计，Token消耗极低。相比其他方案，它避免了扩展连接不稳定、截屏模拟的高Token消耗以及Selenium的代码冗余问题。

2. **技术原理与对比分析**  
   AI操控浏览器主要有四条路径：1. Crowding Chrome（通过扩展操作DOM，Token中等，但易连接失败）；2. Computer Use（通过截屏看像素模拟鼠标键盘，Token消耗爆炸，不建议使用）；3. Selenium（代码量几万行，不适合AI直接调用）；4. Browser Harness（通过WebSocket直连Chrome内核，原生CDP，Token消耗非常低，是为AI量身定做的工具）。

3. **核心功能与Agent Skills机制**  
   Browser Harness允许AI通过CLI发送指令给Daemon，再通过WebSocket控制Chrome。它能复用用户当前浏览器的Cookie和登录状态（如抖音登录）。其独特优势在于‘Agent Helps’文件，初始为空，AI可在运行中自行编写代码填充，持续积累工作经验。仓库自带76个网站的经验技能，AI可‘带技能上线’，形成正反馈循环。

4. **实测案例与Token成本对比**  
   实测案例：通过Claude Code控制Chrome，调用订阅版Midjourney进行出图并下载。步骤包括安装依赖、开启远程调试连接Chrome、调用生图、封装技能。Token对比：传统Computer Use约需1.5万个Token，而Browser Harness仅需约2000 Token。实现了零API成本让AI生成图片，效率显著提升。

## 二、知识关联

### 相关主题

- [[AI工具]]
- [[自动化]]
- [[浏览器自动化]]
- [[开源项目]]
- [[效率优化]]
- [[BrowserHarness]]
- [[AI操控浏览器]]
- [[低Token消耗]]
- [[WebSocket]]
- [[CDP]]

### 相关机构/公司

- [[Browser Harness AI]]

## 三、分段原文

> 以下内容保持博主原意和论述顺序，仅修正明显错别字、ASR 识别错误、标点与断句。

### 1. 项目介绍与背景

大家好，今天给大家分享一个新的仓库叫Browser Harness，它是目前AI操控浏览器最省Token的一条路。这个仓库上线GitHub 15天拿了9400个Star，它一共只有592行的Python代码。它的仓库名称就是这个Browser Harness，团队下面的Browser Harness。

### 2. AI操控浏览器的四条路径对比

目前AI操控浏览器有四条路径，分别是Crowding Chrome、Computer Use、Selenium，还有Browser Harness。Crowding Chrome是通过扩展来操纵的，扩展然后读DOM操作页面，这个Token消耗是中等的，但是受限于扩展，我经常会连不上这个扩展。第二个Computer Use就不建议大家使用了，因为这个是通过截屏来看像素来模拟鼠标键盘，这个Token消耗是爆炸的，大家不要用。第三个这个Selenium它是有几万行代码，不是给AI用的。然后最后就是我们的主角Browser Harness，它通过一根WebSocket，然后指点我们的Chrome内核，一共就600行代码，是为AI而生的，Token消耗非常低，是原生的CDP。就相当于前三个是给人穿的鞋，最后一个是给AI量身定做的。

### 3. 技术原理与复用优势

接下来我讲一下这个Browser Harness的原理。Claude Code通过CLI把指令发送给了Daemon，然后Daemon再通过CDP的WebSocket，然后直接来控制我们的Chrome。它一共四个简单的文件，一共大概也就七八百行代码，现在迭代的版本大概七八百行代码，很简单。然后它能连接你正在用的浏览器，然后你的Cookie啊、登录状态啊，就是你都登录了抖音啊、其他的一些登录状态都是完全可以复用。为什么现在Browser Harness能实现了？它不是技术变了，是前提变了。现在我们的LLM大模型呢，它能够通过截图看坐标，然后也能通过截图判断状态，然后自己还能够写Help函数。所以我们只要让我们的LLM连接这个Chrome就够了。

### 4. Agent Skills与自我进化

下一个优势呢，其实这个Browser Harness，他的优势是他能够自己长肌肉。他有个文件叫Agent Helps，它的开箱是空的，Agent可以自己写代码来进行填充。在你的运行中来持续的积累他的工作的经验。然后仓库中本身带了一些Skill，就是76个网站的经验，就是Agent现在刚开始跑的时候，已经能读取仓库里的一些经验，相当于就是带技能就上线了。第三个就是正反馈的循环，就是你跑的越多越越好用。然后你的Agent能通过这个不断的使用来沉淀他这个使用的经验给大家做分享。

### 5. 实测案例与成本分析

之前我已经进行了全面的实测，我通过CC控制Chrome，然后让他用订阅版的Midjourney来进行出图并下载下来。这个操作过程也不复杂，就分成四步。第一步是安装，pip install claude-code跟uv tools。然后第二步就是连接Chrome，这一步有一个远程调试需要打开。然后第三步是Midjourney的生图，就是CC就能直接操控浏览器，让Midjourney来生图了。第四步，我把它封装成了一个技能。对比传统的Computer Use跟我们的Browser Harness，Computer Use大概需要这个1.5万个Token，然后Browser Harness大概需要2000就可以了。就是通过这种形式呢，我们实现了零API的成本，让你的Midjourney进行这个图片的生成。如果大家需要封装好的技能，可以看我的首页。

### 6. 总结

Browser Harness，他是为AI设计的工具啊，逻辑完全不同，他将判断力从框架转移到了模型，然后15天拿到了9400个Star，是市场在用脚投票的结果。好了，我今天的分享到这里，欢迎大家关注，谢谢大家。

## 四、视频原始转录

> 以下内容由 Whisper 自动转录生成，可能存在错字、断句错误或语义遗漏，请以原视频为准。

大家好，今天给大家分享一个新的仓库叫brower heys,它是目前AI操控浏览器最省token的一条路。这个仓库上线get tuup十五天拿了九千四百个star,它一共只有五百九十二行的python代码。它的仓库名称就是这个brother use团队下面的brother honeys.目前AI操控浏览器有四条路径，分别是crowd in chrome.嗯，它是还还有computer use,还有selenium,还有brother、 honys呃，crowding. Chrome呢它是通过扩展来操纵的扩展，然后读DOM操作页面，这个token消耗是中等的，但是受限于扩展就是我经常会连不上这个扩展。然后第二个computer use就不建议大家使用了，因为这个是通过截屏来看像素来模拟鼠标键盘。呃，这个token消耗是爆炸的，大家不要用。呃，第三个这个selenium它是有几万行代码，不是给AI用的。然后最后就是我们的主角brother er oneys,它通过一根web socket,然后指点我们的chrome内核，一共就六百行。代码是为AI而生的，土口消耗非常低，是原生的CDP,就相当于就前三个是给人穿的鞋。最后是一个是给AI a卷量身定做的。呃，接下来我讲一下这个brother honeys的原理。呃，god code呢通过COI把指令发送给了demon,然后demon呢再通过CDP的web socket,然后直接来控制我们的chrome.他一共四个简单的文件，嗯，一共大概也就七八百行代码。现在迭代的版本大概七八百行代码很简单，然后它能连接你正在用的浏览器。然后你的cookie啊、登录状态啊，就是你都登录了抖音啊，其他的一些登录状态都是完全可以复用。为什么？现在呃brother honey, ys能实现了，它不是技术变了，是前期变了。现在我们的ALM这大模型呢，它能够通过截图看坐标，然后也能通过截图判断状态，然后自己还能够写help函数。所以我们只要让我们的LLM连接这个chrome就够了。呃，是下一个优势呢。其实这个brother汉尼斯，他的优势是他能够自己长肌肉。他有个文件叫agent helps,它的开箱是空的，a卷可以自己写代码来进行填充。在你的运行中来持续的积累他的工作的经验。然后仓库中本身带了一些skill,就是七十六个网站的经验就是a卷。现在刚开始跑的时候，已经能读取仓库里的一些经验，相当于就是带技能就上线了。啊，第三个就是正反馈的循环，就是你跑的越越多越越好用。然后呃你的a卷能通过这个不断的使用来沉淀他这个使用的经验给大家做分享。之前我已经进行了全面的实测，我通过CC控制chrome,然后让他用订阅版的j am来进行了出图并下载下来。这个操作过过程也不复杂，就分成四步。第一步是安装啊，get coron跟UV tools等于识到。然后第二步就是连接chrome这一步，有一个远程调试需要打开。然后第三步是君am奶的生图，就是CC就能直接操控浏览器，让呃dream来生图了。对呀，第四步，我把它封装成了一个技能对比。传统的computer use跟我们的brother honeys computer use大概需要这个一点五万个token.然后巴洛塔里斯大概需要两千就可以了。就是通过这种形式呢，我们实现了零PAPI的成本，让你的呃german进行这个图片的生成。如果大家需要封装好的技能，可以看我的首页。 Brother honeys,他是为AI设计的工具啊，逻辑完全不同，他将判断力从框架转移到了模型，然后十五天拿到了九千四百个star,是市场在用脚投票的结果。好了，我今天的分享到这里，欢迎大家关注，谢谢大家。
