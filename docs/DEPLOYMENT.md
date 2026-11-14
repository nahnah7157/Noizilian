# 배포 가이드

이 저장소는 Flask 앱 하나가 화면과 `/api/chat`을 함께 제공합니다. 먼저 로컬에서 원하는 기능이 동작하는지 확인한 뒤, **공개 URL에서 같은 흐름을 다시 확인**하세요. 현재 코드를 그대로 배포하면 데모 답변만 나옵니다.

**팀의 기획 및 구현에 따라 배포 절차가 달라질 수 있습니다. 그러나 AI를 활용한 질의를 통해 배포까지 진행하시는 경험이 중요하다고 생각합니다. 배포까지 이어지는 과정이 처음이시라면 어색할 수는 있어도 한 번 시도해보시면 이후에는 어려운 작업은 아닐 것입니다.**

**Github repo와 연결하면 바로 url형태로 배포가 가능하기에 이번 기회에 배포까지 진행하는 것에 익숙해지시면 좋겠습니다.**

## 1. 배포 경로 고르기

| 경로 | 현재 구조에서 할 일 | 적합한 경우 |
| --- | --- | --- |
| Render Python 웹 서비스 | [Render 배포 가이드](RENDER-GUIDE.md) | 현재 구조를 그대로 운영하고 싶을 때 |
| Render Docker 웹 서비스 | [Render 배포 가이드](RENDER-GUIDE.md)와 [Docker 개발 가이드](DOCKER-GUIDE.md) | 배포도 컨테이너로 구성하고 싶을 때 |
| Vercel Flask Function | Git 저장소를 가져와 `app.py` 배포 | Function 실행 제약과 데이터 저장 위치를 확인한 경우 |
| 프런트·API 분리 또는 Cloudflare | API 주소·정적 파일·서버 설정 변경 | 제품 구조에 맞게 화면과 서버를 따로 운영할 때 |

Render나 Vercel을 필수 플랫폼으로 지정하지 않습니다. 아래 경로는 **현재 코드 기준의 예시**입니다. 플랫폼의 화면, 요금, 제한은 바뀔 수 있으므로 링크된 공식 문서도 함께 확인하세요.

## 2. 공통 준비

1. [로컬 실행 가이드](LOCAL_SETUP.md)에 따라 채팅 화면에서 메시지를 보내고 답변이 나오는지 확인합니다. 현재 데모라면 API 키가 필요 없습니다.
2. `app.py`, `requirements.txt`, `.python-version`, `config/`, `services/`, `templates/`, `public/`이 저장소 루트에 있는지 확인합니다. `.python-version`은 Python 3.12를 지정합니다.
3. `git status --short`로 올릴 파일을 확인합니다. `git check-ignore .env`가 `.env`를 출력하는지도 확인하세요. **실제 API 키를 `.env.example`, 코드, Markdown, 브라우저 JavaScript, 이슈, 화면 캡처에 적지 마세요.** `.gitignore`는 `.env`와 `.env.*`를 제외합니다.
4. 모델을 연결했다면 필요한 환경 변수의 **이름만** 팀 README에 적습니다. OpenAI API 키는 운영진이 제공합니다. 값을 코드나 저장소에 넣지 말고 배포 플랫폼의 비밀 환경 변수 설정에 입력합니다. `FLASK_DEBUG=1`은 공개 서비스에 사용하지 않습니다.
   공개된 `/api/chat`이 팀의 키로 호출되므로, 실제 모델을 연결한 뒤에는 요청 횟수 제한을 적절히 정합니다.
5. 배포할 Git 저장소에 코드를 반영합니다. 아래 대시보드 절차는 Git 저장소를 연결하는 방식입니다.

키를 실수로 공개했다면 파일 삭제만으로는 부족합니다. 해당 키를 폐기·재발급하고 공유 범위를 확인해야하니 운영진에게 알려주세요.

## 3A. Render

현재 Flask 앱을 Render에 올리는 방법은 두 가지입니다.

- **Python 런타임:** `requirements.txt`를 설치하고 Gunicorn으로 앱을 실행합니다. 처음 배포할 때 설정을 간단히 시작할 수 있습니다.
- **Docker 런타임:** 저장소의 `Dockerfile`로 이미지를 빌드합니다. 배포 환경도 컨테이너로 맞추고 싶을 때 선택하세요.

두 절차의 대시보드 설정, 환경 변수, 공개 URL 확인, 재배포와 문제 해결은 [Render 배포 가이드](RENDER-GUIDE.md)를 따르세요. Docker 이미지 변경과 로컬 검증은 [Docker 개발 가이드](DOCKER-GUIDE.md)에 있습니다. `docker-compose.yml`은 Render에서 실행하지 않는 로컬 개발 설정입니다.

## 3B. Vercel Flask Function

Vercel은 루트 `app.py`의 Flask `app`을 Function으로 인식하고 `public/`의 파일은 정적 자산으로 제공합니다. 현재 `requirements.txt`와 `.python-version`도 함께 배포합니다. [Vercel Flask 가이드](https://vercel.com/docs/frameworks/backend/flask)

1. [Vercel 대시보드](https://vercel.com/dashboard)에서 **Add New → Project**를 열고 Git 저장소를 가져옵니다.
2. **Root Directory**가 `app.py`가 있는 저장소 루트인지 확인합니다. Flask가 감지되면 특별한 이유 없이 Build Command나 Output Directory를 덮어쓰지 않습니다.
3. 실제 모델을 연결했다면 운영진이 제공한 키 등 필요한 값을 **Environment Variables**에 설정합니다.  [Vercel 환경 변수 설정](https://vercel.com/docs/environment-variables/managing-environment-variables)
4. **Deploy**를 누르고 빌드 로그에서 의존성 설치와 Function 생성 결과를 확인합니다.
5. 배포된 `https://….vercel.app` 주소에서 `/`, `/chat`, `/health`, `/assets/css/style.css`, `/assets/js/chatbot.js`, `/assets/images/golden_record_cut.png`를 각각 엽니다.
6. 채팅 화면에서 메시지를 보내고 브라우저 개발자 도구 **Network**에서 `POST /api/chat`의 상태 코드와 응답을 확인합니다.

로컬 Flask는 `public/`을 직접 제공하지만 Vercel에서는 `public/`이 CDN의 정적 자산 경로입니다. 앱은 Vercel의 `VERCEL=1` 환경 변수가 있으면 Flask의 정적 파일 라우트를 끄고 같은 `/assets/...` 주소를 사용합니다. 프로젝트에서 시스템 환경 변수 자동 노출을 껐다면 다시 켜거나 `VERCEL=1`을 환경 변수로 설정하세요. 화면만 확인하지 말고 CSS·JS·이미지 URL도 확인해야 합니다. Function의 실행 시간·패키지 크기·파일 저장 제약은 [Vercel Flask 제한](https://vercel.com/docs/frameworks/backend/flask#limitations)에서 확인합니다. 요청 중 생성하는 인덱스나 대화 기록을 Function의 로컬 파일에만 저장하지 마세요. [Vercel 시스템 환경 변수](https://vercel.com/docs/environment-variables/system-environment-variables)

## 3C. 프런트·API 분리 또는 Cloudflare

프런트를 다른 서비스에 두면 브라우저 JS의 `fetch("/api/chat")`을 새 API 주소 또는 프록시 경로로 바꾸고, 서버의 허용 출처와 쿠키·인증 방식을 맞춰야 합니다. **API 키는 브라우저 코드나 공개 프런트 환경 변수에 넣지 않습니다.** 프런트와 서버를 각각 배포한 뒤 두 공개 URL을 연결해 확인하세요.

Cloudflare에서 현재 Flask 앱을 실행하려면 Worker 진입점·설정·정적 파일 배치·Python 패키지 호환성을 따로 검토해야 합니다. Cloudflare에 정적 프런트를 두고 Flask API를 다른 플랫폼에 배포하는 구성도 가능합니다. [Cloudflare Flask Worker 가이드](https://developers.cloudflare.com/workers/framework-guides/apis/flask/), [Python 패키지 안내](https://developers.cloudflare.com/workers/languages/python/packages/)

## 4. 공개 URL에서 최종 확인

- [ ] `/`, `/chat`, `/health`와 CSS·JS·이미지가 열립니다.
- [ ] 대화가 실제 답변을 반환합니다. **데모 문구만 나오면 모델 연결은 미완성**입니다.
- [ ] 이미지 선택을 구현했다면 답변에 맞는 이미지가 나오고 URL을 새 창에서도 열 수 있습니다.
- [ ] 자료가 있는 질문·없는 질문, 모델 API 실패에서 응답과 안내가 적절합니다.
- [ ] 로그와 브라우저 Network에 실제 키나 개인정보가 드러나지 않습니다.
- [ ] 재배포·재시작 후에도 필요한 자료와 기록이 유지됩니다.
- [ ] 공개 URL을 제출·시연에 사용할 수 있게 확인했고, 팀 README에 실행 방법, 환경 변수 **이름**, 알려진 제한을 적었습니다.

빌드 실패 시 **Root Directory → Python 버전 → `requirements.txt` → 빌드 로그** 순서로 확인하세요. 화면은 열리는데 채팅이 실패하면 Network의 `/api/chat` 상태 코드, 서버 로그, 환경 변수의 **설정 여부**를 확인합니다. 로그나 질문 글에 키의 실제 값을 붙이지 마세요.
