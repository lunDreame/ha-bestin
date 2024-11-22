## BESTIN 1.0

### Gateway 1.0 기본 버전
- 사진처럼 결선 
- `CTRL 485A, CTRL 485B`: EW11 A, B / `ENERGY 485A, ENERGY 485B`: EW11 A, B

#### 출처: https://yogyui.tistory.com/
![Gateway 1.0 기본](/images/gateway1.0_default.png)

### Gateway 1.0 구형 버전
- 사진상의 게이트웨이인 경우, **RS485B** 부분에 결선하세요.
- 남는 랜선 한쪽은 RS485B 포트에 연결하고, 다른 한쪽은 8가닥으로 정리한 뒤, 흰파, 파 선을 EW11의 A와 B에 각각 연결하세요.
![Gateway 1.0 구형](/images/gateway1.0_old.png)

### Gateway 1.0 일체형 버전
### 준비물
- Y형 랜선 커플러
  - [칼론 랜선 Y형 연장 랜커플러](https://www.coupang.com/vp/products/1824088908?itemId=3103992445&vendorItemId=71091768474&q=y%EC%BB%A4%ED%94%8C%EB%9F%AC&itemsCount=36&searchId=e8329a1950ca4edea46ae93a242c7dc9&rank=1&isAddedCart=)
  - [Coms 커플러(RJ45)](https://www.coupang.com/vp/products/2014821857?itemId=3427497334)
  - 첫 번째 제품은 가성비가 좋으나 내구성과 불량률이 있을 수 있습니다.

### 작업 절차

1. **랜선 브릿지 작업**
   - 월패드 후면의 CTRL 랜선을 Y 커플러를 사용하여 브릿지합니다.

2. **연결 방법**
   - Y 커플러의 **모아지는 부분**에 기존 월패드에 연결된 랜선을 꽂습니다.
   - **분배되는 부분** 중 한곳에 새로운 랜선을 연결한 후, 해당 랜선을 월패드의 기존 랜 포트에 연결합니다.
   - **분배되는 부분**의 다른 한쪽에 연결된 랜선은 반대쪽 끝을 잘라내어 8가닥으로 정리합니다.

3. **EW11 결선**
   - 8가닥 중에서 아래와 같이 EW11의 A, B 포트에 결선합니다:
     - 흰주, 주: **EW11의 A, B**
     - 흰파, 파: **EW11의 A, B**
    
### 주의사항
- 환경에 따라 랜선의 색상 또는 종류가 다를 수 있으니, 이를 확인한 후 작업을 진행하세요.

![Gateway 1.0 일체형](/images/gateway1.0_aio.png)

## BESTIN 2.0

### Gateway 2.0 기본 버전
- 사진처럼 포트가 나눠져 있는 경우, 에너지콘트롤러/미세먼지센서 포트에 각각 랜선을 연결하세요.
- 연결 방법은 [Gateway 1.0 일체형 버전](#작업-절차)과 동일합니다. 단, 에너지콘트롤러/미세먼지센서에 연결하여 브릿지 하세요.
- 예외로 포트가 비어있는 경우가 있습니다. 이 경우 브릿지 없이 바로 연결하시면 됩니다.

![Gateway 2.0 기본](/images/gateway2.0_default.png)

![Gateway 2.0 기본 연결](/images/gateway2.0_default_connect.png)

### Gateway 2.0 신형 버전
- 사진을 참고하여 디밍 세대인지 확인해 보세요.
- 추가적인 패킷 데이터에 대한 제보를 기다립니다.
  - [디밍 테스트](/tests/dimming_test.py) 코드를 사용하여 좀 더 세부적으로 분석이 가능합니다.
- **Gateway 2.0 기본 버전**과 결선은 같으며 에너지콘트롤러 EW11의 경우 buadrate를 38,400로 설정해 주세요! (EW11 IP 접속 -> SERIAL PORT SETTINGS -> Buad Rate)

![Gateway 2.0 디밍](/images/gateway2.0_dimming.png)

![Gateway 2.0 에너지콘트롤러](/images/gateway2.0_energy_controller.png)
